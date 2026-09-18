"""Разбор страниц Confluence (markdown) в карточки платы и ревизии.

Страницы двух видов, и отличаются они по содержимому, а не по имени файла:

* страница ревизии — «Карточка печатного узла», чек-листы, ссылки на папки;
* страница платы — «Описание» с краткой характеристикой и список версий.

Одна страница — одна ревизия: карточка печатного узла, чек-листы и ссылки
на папки. Разбор отделён от записи в базу: страницы верстают люди, и
разметка у них разъезжается от ревизии к ревизии — чинить приходится
именно разбор, и делать это проще там, где нет ни моделей, ни транзакций.

Разъехалось, на пяти страницах одной платы:

* карточка бывает таблицей ``| **Ключ** | значение |``, а бывает сплошным
  текстом, где ключи идут жирным подряд и без переводов строк;
* у чек-листов три разных набора колонок: с «Форматом» и «Приоритетом», с
  одним «Форматом» и вовсе без них;
* номера разделов плавают: «Прикреплённые документы» бывают разделом 4, 5
  и 6, поэтому раздел ищется по названию, а не по номеру;
* в ячейке «Наличие» вместо ответа часто стоит сам список вариантов
  («✕ / ❌ / Ревью / ✅») — это шаблон, а не заполненное значение.

Последнее важнее прочего: принять список вариантов за ответ значит
проставить готовность там, где её не проверяли.
"""

import re

# Ответы в колонке «Наличие документа»
STATUSES = {
    "✅": "ok",
    "❌": "no",
    "✕": "na",
    "❗": "attention",
    "ревью": "review",
}

# Заголовок чек-листа -> группа. Ищем по куску названия: номера разделов
# на страницах разные, а формулировки устойчивы
GROUPS = (
    ("исходных файлов", "source"),
    ("производства печатной платы", "pcb"),
    ("smt", "smt"),
    ("ркд", "rkd"),
)

# Строка раздела «Прикреплённые документы» -> поле ревизии
LINKS = (
    ("source", "source_dir_url"),
    ("manufacture", "manufacture_url"),
    ("assembly", "assembly_url"),
    ("testing", "testing_dir_url"),
    ("матриц", "test_matrix_url"),
    ("ескд", "eskd_dir_url"),
    ("эталонный bom", "reference_bom_url"),
)

# Поле карточки -> поле ревизии
CARD = {
    "наименование печатной платы (pcb)": "pcb_name",
    "наименование bom": "bom_name",
    "обозначение на шелкографии": "silkscreen",
    "децимальный номер узла печатного (pcba)": "decimal_pcba",
    "децимальный номер печатной платы (pcb)": "decimal_pcb",
    "вид печатной платы (из пп рф №719)": "pcb_type",
    "наименование ресурсной спецификации (1с)": "spec_1c",
    "ссылка на ресурсную спецификацию (1с)": "spec_1c_url",
    "fru-шаблон модели печатного узла (megarac)": "fru_megarac",
    "fru-шаблон модели печатного узла (oybmc)": "fru_oybmc",
}

# Числовые поля. В выгрузке они приходят с хвостом («2 шт», «140 баллов»),
# поэтому берётся первое число, а не значение целиком
NUMBERS = {
    "количество плат в мультизаготовке": "panel_count",
    "количество баллов": "points",
}

# Поля страницы платы (не ревизии). Наименование и описание разбираются
# отдельно, разметкой; здесь — то, что записано обычной парой «ключ —
# значение»
BOARD_FIELDS = {
    "компания-разработчик": "developer",
}

# «Бэкплейн HSBP-4L.01» -> backplane. Тип платы отдельным полем на
# страницах не записан, зато он стоит первым словом полного наименования.
# Список закрытый: в реестре по типу фильтруют, и свободный ввод развалил
# бы фильтр на «бэкплейн», «Бэкплейн» и «backplane»
TYPE_WORDS = (
    ("материнск", "motherboard"),
    ("бэкплейн", "backplane"),
    ("бекплейн", "backplane"),
    ("райзер", "riser"),
    ("интерпозер", "interposer"),
    ("адаптер", "adapter"),
    ("управлен", "control"),
    ("индикац", "indicator"),
    ("питания", "power"),
)


def board_type_of(name):
    """Тип платы по её полному наименованию. Не опознали — пустая строка."""
    lowered = (name or "").lower()
    for word, kind in TYPE_WORDS:
        if word in lowered:
            return kind
    return ""

# Значения-заглушки: поле в шаблоне есть, данных нет. «Не требуется» сюда
# не входит — это ответ, а не пустота
EMPTY = {
    "", "-", "—", "?", "??", "???", "????", "?????", "✕", "❌", "✅", "❌/✅",
    "ссылка на раздел в confluence", "ссылка на ресурсную спецификацию",
    "ссылка на confluence", "добавить ссылку", "полное название печатного узла",
    "в проработке",
}

LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# то же, но с адресом: из него нужно имя файла
IMAGE_SRC = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
TABLE_FIELD = re.compile(r"^\|\s*\*\*(?P<key>[^*]+?)\*\*\s*\|(?P<value>.*?)\|?\s*$")
LOOSE_FIELD = re.compile(r"\*\*(?P<key>[^*]{3,80}?)\*\*(?P<value>[^*]*)")


def image_names(text):
    """Имена файлов картинок со страницы, по порядку появления.

    Только имена: и относительный путь ``./attachments/plate.png``, и
    полный адрес Confluence ``https://…/download/attachments/79038644/
    plate.png?version=1`` ведут к одному файлу, который лежит рядом с
    выгруженным markdown. Адрес отбрасываем, строку запроса тоже.

    Порядок важен: первая картинка — Top side, вторая — Bottom. Другого
    признака стороны на страницах нет — ни подписи под картинкой, ни
    осмысленного имени файла (``image-2026-1-23_11-36-51.png``), — а в
    таблице «Изображение печатной платы» колонки идут именно так.

    Лишнего не отсеиваем: на странице попадаются и служебные картинки
    Confluence (значок ожидания в блоке загрузки файлов). Отсеет их тот,
    кто ищет файлы на диске: служебных среди вложений нет.
    """
    found = []
    for address in IMAGE_SRC.findall(text or ""):
        name = address.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        if name and name not in found:
            found.append(name)
    return found


def clean(text):
    """Снимает разметку, оставляя видимый текст."""
    text = IMAGE.sub("", text or "")
    text = LINK.sub(r"\1", text)
    text = text.replace("<br>", " ").replace("\xa0", " ")
    text = re.sub(r"\\(.)", r"\1", text)          # markdown-экранирование
    # подчёркивания не трогаем: в путях на диск R они значимы
    # (R:\2_PCB_DESIGN), а курсив в этих ячейках задан звёздочками
    text = re.sub(r"[*`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def plain(text):
    """Текст без markdown-экранирования, но со звёздочками.

    Нужен колонке «Формат»: там звёздочка — часть значения (``*.xlsx``), а
    не курсив, и общая очистка её бы съела.
    """
    text = LINK.sub(r"\1", text or "")
    text = text.replace("<br>", " ").replace("\xa0", " ")
    text = re.sub(r"\\(.)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def value(text):
    """Значение ячейки; заглушки превращаются в пустую строку."""
    cleaned = clean(text)
    return "" if cleaned.lower() in EMPTY else cleaned


def link_of(text):
    """Ссылка из ячейки: сначала markdown-ссылка, потом путь на диск R."""
    found = LINK.search(text or "")
    if found and found.group(2):
        return found.group(2).strip()
    path = clean(text)
    return path if re.match(r"^[A-ZА-Я]?R:\\", path) else ""


def status_of(text):
    """Ответ в колонке «Наличие» — или пусто, если там список вариантов."""
    cleaned = clean(text).lower()
    found = {code for mark, code in STATUSES.items() if mark in cleaned}
    # «✕ / ❌ / Ревью / ✅» — это перечень возможных ответов из шаблона:
    # принять его за ответ значит проставить готовность, которой нет
    return found.pop() if len(found) == 1 else ""


def _rows(lines, start):
    """Строки markdown-таблицы, начиная со строки заголовка."""
    table = []
    for line in lines[start:]:
        if not line.lstrip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(set(cell) <= {"-", " ", ":"} for cell in cells):
            continue                       # разделитель шапки
        table.append(cells)
    return table


def _columns(header):
    """Номера колонок по названиям шапки — их набор на страницах разный."""
    layout = {}
    for index, cell in enumerate(header):
        name = clean(cell).lower()
        for key, marker in (("title", "название документа"),
                            ("format", "формат"),
                            ("responsibility", "зона ответственности"),
                            ("priority", "приоритет"),
                            ("status", "наличие"),
                            ("comment", "комментарий")):
            if marker in name and key not in layout:
                layout[key] = index
    return layout


def card_fields(text):
    """Поля карточки. Понимает оба формата — таблицей и сплошным текстом."""
    found = {}
    for line in text.splitlines():
        match = TABLE_FIELD.match(line)
        if match:
            key = clean(match.group("key")).lower()
            if key:
                found.setdefault(key, (match.group("value"), value(match.group("value"))))

    for match in LOOSE_FIELD.finditer(text):
        key = clean(match.group("key")).lower()
        raw = match.group("value")
        if key and "|" not in raw and len(raw) < 400:
            found.setdefault(key, (raw, value(raw)))
    return found


def checklists(text):
    """Строки чек-листов по группам."""
    lines = text.splitlines()
    rows, group = [], None

    for index, line in enumerate(lines):
        heading = re.match(r"^#{2,4}\s*[\d. \\]*(.+?)\s*:?\s*$", line)
        if heading and "чек-лист" in heading.group(1).lower():
            name = heading.group(1).lower()
            group = next((code for marker, code in GROUPS if marker in name),
                         "other")
            continue
        if group is None or not line.lstrip().startswith("|"):
            continue
        if "название документа" not in clean(line).lower():
            continue

        table = _rows(lines, index)
        if not table:
            continue
        layout = _columns(table[0])
        if "title" not in layout:
            continue

        for cells in table[1:]:
            def cell(key):
                position = layout.get(key)
                return cells[position] if position is not None and position < len(cells) else ""

            title = value(cell("title"))
            # строки-разделители: путь к папке на диске R и подпись
            # «Второй приоритет» — это не документы
            if (not title or title.lower().startswith(("r:", "дr:"))
                    or "сетевом хранилище" in title.lower()
                    or title.lower().startswith("второй приоритет")):
                continue

            rows.append({
                "group": group,
                "title": title,
                "file_format": plain(cell("format")),
                "responsibility": clean(cell("responsibility")),
                "status": status_of(cell("status")),
                "comment": value(cell("comment")),
                "url": link_of(cell("comment")),
            })
    return rows


def links(text):
    """Раздел «Прикреплённые документы / ссылки»."""
    lines = text.splitlines()
    found = {}
    for index, line in enumerate(lines):
        if "документ / ссылка" not in clean(line).lower():
            continue
        for cells in _rows(lines, index)[1:]:
            if len(cells) < 2:
                continue
            name = clean(cells[0]).lower()
            target = link_of(cells[1]) or value(cells[1])
            if not target:
                continue
            for marker, field in LINKS:
                if marker in name:
                    found.setdefault(field, target)
                    break
    return found


def approval(text):
    """Шапка страницы: утверждена карточка или ещё в работе."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "статус страницы продукта" not in clean(line).lower():
            continue
        table = _rows(lines, index)
        for cells in table[1:]:
            status = clean(cells[0]) if cells else ""
            date = clean(cells[1]) if len(cells) > 1 else ""
            # «❌/✅» — перечень вариантов из шаблона, а не ответ
            return {"approved": status == "✅", "approved_at": date}
    return {"approved": False, "approved_at": ""}


def parse(text, name=""):
    """Страница -> данные ревизии. Номер берётся из заголовка, а не из имени файла."""
    title = text.split("\n", 1)[0]
    number = clean(title.lstrip("# ")) if title.startswith("#") else name

    fields = card_fields(text)
    card, numbers = {}, {}
    for key, (raw, cleaned) in fields.items():
        if key in CARD and cleaned:
            # у ссылок берём адрес, а не подпись
            card[CARD[key]] = (link_of(raw) or cleaned) if key.startswith(
                ("ссылка", "fru")) else cleaned
        if key in NUMBERS:
            digits = re.match(r"\d+", cleaned)
            if digits:
                numbers[NUMBERS[key]] = int(digits.group())

    # полное наименование описывает саму плату и одинаково у всех её
    # ревизий; тип выводим из него же
    full_name = fields.get("полное наименование", ("", ""))[1]

    return {
        "number": number,
        "name": full_name,
        "board_type": board_type_of(full_name),
        "card": card,
        "images": image_names(text),
        "numbers": numbers,
        "links": links(text),
        "checklist": checklists(text),
        **approval(text),
    }


# ---- страница платы -------------------------------------------------------

# «Бэкплейн HSBP-5S01 - это бэкплейн с 5 SFF слотами» — до тире стоит
# полное наименование платы, ровно в том виде, в каком его пишут в
# карточках ревизий
NAME_RE = re.compile(r"^(?P<name>.{3,80}?)\s+[-—–]\s+это\b")


def section(text, marker):
    """Кусок страницы под заголовком, в названии которого есть marker."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        heading = re.match(r"^#{2,4}\s*[\d. \\]*(.+?)\s*:?\s*$", line)
        if not heading:
            continue
        if start is None and marker in heading.group(1).lower():
            start = index + 1
        elif start is not None:
            return "\n".join(lines[start:index])
    return "\n".join(lines[start:]) if start is not None else ""


def board_card(text):
    """Раздел «Описание» -> назначение, применяемость и характеристика.

    Пункты разложены по смыслу, а не по порядку: первый абзац описывает
    саму плату, отдельный пункт — куда она ставится, а всё, что идёт под
    «Краткой характеристикой», — это характеристика. Вложенность в ней
    сохраняется: у разъёмов и светодиодов свои подпункты, и без отступов
    список разваливается в кашу.
    """
    block = section(text, "описание")
    purpose, applicability, specs = [], [], []
    specs_indent, in_specs = None, False

    for line in block.splitlines():
        if not line.strip().startswith("*"):
            continue
        indent = len(line) - len(line.lstrip())
        item = clean(line.lstrip("* \t"))
        if not item:
            continue

        if "краткая характеристика" in item.lower():
            in_specs, specs_indent = True, indent
            continue
        if in_specs and indent <= specs_indent:
            in_specs = False           # список кончился, пошли обычные пункты

        if in_specs:
            # отступ считаем от корня списка: «Разъемы:» и его подпункты
            depth = max(0, (indent - specs_indent) // 4 - 1)
            specs.append("    " * depth + item)
        elif item.lower().startswith(("предназначен", "применяет",
                                      "устанавливает")):
            applicability.append(item)
        else:
            purpose.append(item)

    return {
        "purpose": "\n".join(purpose),
        "applicability": "\n".join(applicability),
        "specs": "\n".join(specs),
    }


def is_board_page(text):
    """Страница платы, а не ревизии.

    Опознаём по содержимому: имя файла ничего не говорит, а «Список версий
    печатных плат» есть только на странице платы — ревизия сам себя в
    список версий не включает.
    """
    lowered = text.lower()
    if "карточка печатного узла" in lowered:
        return False
    return "список версий печатных плат" in lowered


def parse_board(text, name=""):
    """Страница платы -> данные карточки."""
    title = text.split("\n", 1)[0]
    number = clean(title.lstrip("# ")) if title.startswith("#") else name

    card = board_card(text)
    first = card["purpose"].split("\n", 1)[0]
    match = NAME_RE.match(first)
    name = match.group("name").strip() if match else ""

    # то, что записано парой «ключ — значение», а не разметкой списка
    fields = card_fields(text)
    extra = {target: fields[key][1]
             for key, target in BOARD_FIELDS.items()
             if key in fields and fields[key][1]}

    return {
        "number": number,
        "name": name,
        "board_type": board_type_of(name),
        "images": image_names(text),
        **extra,
        **card,
    }
