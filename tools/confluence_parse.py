"""Разбор выгрузки Confluence в промежуточный JSON.

Зачем отдельный шаг, а не сразу запись в базу. Выгрузку делают люди и
делают её редко: разметка страниц разъезжается, поля переименовывают,
часть карточек оформлена вовсе не таблицей. Разбор такого источника — это
то, что придётся править чаще всего, и держать его отдельно от записи в
базу дешевле: JSON можно посмотреть глазами до того, как что-то попадёт в
таблицы, а при следующей выгрузке чинить придётся только этот файл.

Что разбирается:

* карточки моделей изделий  -> позиции типа «сервер» + состав из блока
  «Материнская плата / Бэкплейны / Райзер / Другие платы»;
* страницы плат со списком версий -> позиции типа «плата»;
* карточки печатных узлов   -> ревизии плат (номер уже содержит ревизии,
  разбирает их boards.revisions.parse_pn);
* карточки кабелей          -> позиции типа «кабель» с длиной и типом.

Чего здесь нет намеренно: чек-листы, матрицы тестового покрытия и списки
документов. Это документооборот, а не состав.

Запуск:

    python tools/confluence_parse.py ./confluence -o confluence.json
"""

import argparse
import json
import pathlib
import re
import sys
from collections import Counter

# Скрипт работает без Django — поэтому и запускается отдельно, — но правило
# записи партномера у нас одно на весь проект. boards/pn.py Django не тянет,
# так что достаточно положить корень репозитория в путь поиска: скрипт
# запускают из него (см. «Запуск» выше).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from boards.pn import match_key  # noqa: E402  (после правки sys.path)

# Значения-заглушки. В выгрузке их много: поле заведено, а данных нет.
# Записать их как значения хуже, чем не записать ничего: потом не отличить
# настоящий децимальный номер от «?????».
PLACEHOLDERS = {
    "", "-", "—", "?", "??", "???", "????", "?????", "✕", "❌", "✅", "❌/✅",
    "ссылка на раздел в confluence", "ссылка на confluence",
    "добавить ссылку", "ссылка на номенклатуру",
    "ссылка на ресурсную спецификацию", "не требуется", "n/a",
}

# по этим строкам страница опознаётся: у каждого типа своя карточка
# Заголовки самих карточек: как ключ поля они бессмысленны, а в разбор
# попадают, потому что оформлены тем же жирным начертанием
NOT_FIELDS = {"Карточка кабеля", "Карточка печатного узла",
              "Карточка изделия", "Карточка"}

MARKERS = (
    ("cable", "Карточка кабеля"),
    ("board_revision", "Карточка печатного узла"),
    ("server", "Карточка изделия"),
    ("board", "Список версий печатных плат"),
)

LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")          # [текст](ссылка) -> текст
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
TABLE_FIELD = re.compile(r"^\|\s*\*\*(?P<key>.+?)\*\*\s*\|(?P<value>.*?)\|?\s*$")
# «рыхлый» формат новых страниц: **Ключ** значение **Ключ** значение,
# иногда вообще без переводов строк между ними
LOOSE_FIELD = re.compile(r"\*\*(?P<key>[^*]{3,80}?)\*\*\s*(?P<value>[^*]*)")
# «2 х HSBP-5S.01-R», «2 x HSRB-CDFP.01»
QUANTITY = re.compile(r"(\d+)\s*[хx]\s*\[?\s*([A-Za-z][A-Za-z0-9.\-]+)")
# Граница слева задана явным списком, а не \b: в тексте встречается
# «2 хHSBP-5S.01-R» — кириллическая «х» для \b такой же символ слова, как
# латинская буква, и номер после неё не находился бы
PART_NUMBER = re.compile(
    r"(?<![A-Za-z0-9-])(HS[A-Z]{1,3}-[A-Z0-9.]{2,14}(?:-[A-Z0-9]{1,4})*)")


def clean(text):
    """Убирает разметку: ссылки, картинки, переводы строк, лишние пробелы."""
    text = IMAGE.sub("", text or "")
    text = LINK.sub(r"\1", text)
    text = text.replace("<br>", " ")
    # в выгрузке экранировано markdown-ом: R:\\5\_CABLES -> R:\5_CABLES.
    # Просто выбросить обратные косые нельзя: в путях на диск R они значимы
    text = re.sub(r"\\(.)", r"\1", text)
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def usable(value):
    """Значение, которое имеет смысл записывать."""
    text = clean(value)
    return "" if text.lower() in PLACEHOLDERS else text


def title_of(text):
    """Заголовок страницы — первая строка вида «# Название»."""
    first = text.split("\n", 1)[0]
    return clean(first.lstrip("# ")) if first.startswith("#") else ""


def kind_of(text):
    for kind, marker in MARKERS:
        if marker in text:
            return kind
    return None


def is_field(key, value):
    """Пара ключ-значение, похожая на поле карточки, а не на мусор.

    Жирным в выгрузке размечены и настоящие поля, и заголовки таблиц, и
    пути на диск R, и сообщения об ошибках макросов Confluence
    («MultiExcerpt ... не найден»). Отличаем по форме ключа.
    """
    return (key and value and key not in NOT_FIELDS and len(key) < 60
            and "MultiExcerpt" not in key and ":\\" not in key
            and "|" not in key)


def fields_of(text):
    """Поля карточки. Понимает оба формата — таблицей и рыхлым текстом.

    Таблица разбирается первой: она точнее, потому что значение ограничено
    ячейкой. Рыхлый формат добирает то, чего в таблице не оказалось, —
    там значение обрывается по следующему жирному ключу, и в него может
    затечь лишнее, поэтому им не перекрываем уже найденное.
    """
    found = {}
    for line in text.splitlines():
        match = TABLE_FIELD.match(line)
        if match:
            key, value = clean(match.group("key")), usable(match.group("value"))
            if is_field(key, value):
                found.setdefault(key, value)

    for match in LOOSE_FIELD.finditer(text):
        key, value = clean(match.group("key")), usable(match.group("value"))
        # «|» в значении означает, что в него затекла соседняя таблица:
        # у рыхлого формата значение обрывается только следующим ключом
        if is_field(key, value) and "|" not in value and len(value) < 300:
            found.setdefault(key, value)
    return found


def base_pn(part_number):
    """Приводит партномер к общему корню.

    В выгрузке одна и та же плата пишется по-разному: HSBP-4L.01,
    HSBP-4L01, HSBP-4L.01-R-01B. Точки в номере — оформление, хвост
    «-01B» — конкретная ревизия. Исполнение «-R» частью корня остаётся: это
    другая плата (другой поставщик, другая сборка), а не её ревизия.
    """
    return re.sub(r"-\d{1,4}[A-Z]$", "", match_key(part_number))


def composition(text):
    """Состав модели из блока «Материнская плата ... Другие платы».

    Количество берётся из записей вида «2 х HSBP-5S.01-R»; где его нет —
    единица. Номера приводятся к корню: строка состава привязывается к
    плате, а не к её ревизии, — конкретная ревизия из ссылки уходит в
    примечание строки.
    """
    if "Материнская плата" not in text:
        return []
    block = text.split("Материнская плата", 1)[1].split("Разработчики", 1)[0]
    # только видимый текст: в адресах ссылок стоит конкретная ревизия
    # (.../HSFP-SCM.01-R-01B), и без очистки он попадал бы в состав
    # отдельной строкой — рядом с той же платой, названной в тексте
    block = clean(block)

    quantities = {base_pn(m.group(2)): int(m.group(1))
                  for m in QUANTITY.finditer(block)}
    lines, seen = [], set()
    for match in PART_NUMBER.finditer(block):
        written = match.group(1)
        root = base_pn(written)
        if root in seen:
            continue
        seen.add(root)
        lines.append({"child": root, "quantity": quantities.get(root, 1),
                      "comment": written if written.upper() != root else ""})
    return lines


def parse_page(path, root):
    """Одна страница -> позиция и её состав, либо None для индексов."""
    text = path.read_text(encoding="utf-8")
    kind = kind_of(text)
    name = title_of(text)
    if not kind or not name:
        return None
    # шаблоны страниц лежат рядом с настоящими и размечены так же
    if name.startswith("Шаблон") or "Шаблон страницы" in name:
        return None

    fields = fields_of(text)
    item = {
        "oy_pn": name,
        "kind": kind,
        "name": fields.get("Полное наименование")
                or fields.get("Полное наименование (партномер)") or name,
        "fields": fields,
        "source": str(path.relative_to(root)).replace("\\", "/"),
    }
    return item, composition(text) if kind == "server" else []


def parse(root):
    root = pathlib.Path(root)
    items, bom, problems = [], [], []

    for path in sorted(root.rglob("*.md")):
        parsed = parse_page(path, root)
        if parsed is None:
            continue
        item, lines = parsed
        items.append(item)
        for line in lines:
            bom.append({"parent": item["oy_pn"], **line})

    # состав должен ссылаться на то, что мы завели: строки, для которых
    # позиции нет, — это не ошибка разбора, а неполнота выгрузки, и знать
    # о них нужно до записи в базу
    known = {base_pn(item["oy_pn"]) for item in items}
    for line in bom:
        if line["child"] not in known:
            problems.append({"kind": "нет страницы", "parent": line["parent"],
                             "child": line["child"]})

    duplicates = [pn for pn, count in Counter(
        item["oy_pn"] for item in items).items() if count > 1]
    problems += [{"kind": "повтор партномера", "oy_pn": pn} for pn in duplicates]

    return {"items": items, "bom": bom, "problems": problems}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="каталог выгрузки Confluence")
    parser.add_argument("-o", "--out", default="confluence.json")
    args = parser.parse_args()

    data = parse(args.root)
    pathlib.Path(args.out).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    kinds = Counter(item["kind"] for item in data["items"])
    print(f"позиций: {len(data['items'])} " + ", ".join(
        f"{kind}: {count}" for kind, count in sorted(kinds.items())))
    print(f"строк состава: {len(data['bom'])}")
    print(f"замечаний: {len(data['problems'])}")
    for problem in data["problems"][:20]:
        print("   ", problem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
