"""Сопоставление внешних ссылок с компонентами по артикулу.

Задача в трекере называется свободным текстом: «Создание транзистора
MMBT3904-7-F», «Соединитель Gold finger DDR5», «ИндуктивностьWPN4020H3R3MT».
Разбирать такое по шаблону «тип + артикул» бесполезно — артикул бывает из
нескольких слов, со скобками и пробелами, а иногда приклеен к слову без
пробела вовсе.

Поэтому текст не разбирается, а сверяется с базой: из названия берутся все
возможные куски, и побеждает самый длинный, который нашёлся среди артикулов
библиотеки. База здесь — источник истины, а не догадка о формате строки.
"""

import csv
import io
import re
from difflib import SequenceMatcher

from django.db import transaction

from .db import unavailable
from .matching import usable
from .refs import component_url
from .registry import CATEGORIES, category_by_table, scan

MATCH_VENDOR = "Vendor PN"
MATCH_GBT = "GBT PN"

# кусок текста короче этого артикулом быть не может
MIN_CANDIDATE = 2

# в артикулах есть латиница или цифры; чисто русские слова — это описание
HAS_PN_CHARS = re.compile(r"[A-Za-z0-9]")

# граница «русское слово вплотную к артикулу»: ИндуктивностьWPN4020H3R3MT
GLUED = re.compile(r"(?<=[А-Яа-яЁё])(?=[A-Z0-9])")


def build_index():
    """Артикулы всей библиотеки: ``{нормализованный артикул: [(таблица, id)]}``.

    Два словаря — по Vendor PN и по GBT PN. Ключ приведён к нижнему
    регистру, а значение хранит исходное написание артикула и список
    записей: один и тот же артикул встречается в нескольких таблицах
    (например, в основной и в заменах), и решать, что с этим делать,
    должен вызывающий.

    ``{ключ: {"pn": как записано в базе, "targets": [(таблица, id)]}}``
    """
    by_vendor, by_gbt = {}, {}

    for category, values in scan(("id", "vendor_pn", "gbt_pn")):
        target = (category.table, values["id"])
        for field, index in (("vendor_pn", by_vendor), ("gbt_pn", by_gbt)):
            original = usable(values.get(field))
            if not original:
                continue
            entry = index.setdefault(original.lower(),
                                     {"pn": original, "targets": []})
            entry["targets"].append(target)

    return by_vendor, by_gbt


def candidates(text):
    """Куски названия, которые могут оказаться артикулом.

    Возвращает их в порядке проверки: сначала самые длинные, среди равных —
    те, что ближе к концу строки. Артикул почти всегда в конце, а длинный
    кусок надёжнее короткого: «WR06X472 JTL» — это один артикул, а не
    «WR06X472» и мусор после него.
    """
    # неразрывный пробел в выгрузке трекера встречается сплошь и рядом
    cleaned = re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
    if not cleaned:
        return []
    # «ИндуктивностьWPN4020H3R3MT» → «Индуктивность WPN4020H3R3MT»
    cleaned = GLUED.sub(" ", cleaned)

    tokens = cleaned.split(" ")
    found = []
    for length in range(len(tokens), 0, -1):
        for start in range(len(tokens) - length, -1, -1):
            piece = " ".join(tokens[start:start + length]).strip(" -–—:,")
            if len(piece) < MIN_CANDIDATE or not HAS_PN_CHARS.search(piece):
                continue
            if piece not in found:
                found.append(piece)
    return found


def match(text, index):
    """Ищет компоненты по названию задачи.

    Возвращает ``(список (таблица, id), артикул, правило)``. Если ничего не
    нашлось — пустой список и пустые строки.

    Vendor PN проверяется раньше GBT PN: в этих задачах пишут именно
    артикул производителя, а совпадение по внутреннему номеру — запасной
    путь для случаев, когда в названии оказался он.
    """
    by_vendor, by_gbt = index

    for piece in candidates(text):
        key = piece.lower()
        for source, rule in ((by_vendor, MATCH_VENDOR), (by_gbt, MATCH_GBT)):
            entry = source.get(key)
            if entry:
                return list(entry["targets"]), piece, rule
    return [], "", ""


# --- чтение файла и запись результатов ------------------------------------
#
# Ниже — то, чем пользуются и команда `manage.py import_links`, и страница
# импорта в веб-интерфейсе. Логика одна: разойтись им нельзя, иначе
# «посмотрел через браузер» и «загрузил командой» дадут разный результат.

URL_COLUMN = "Ключ"
TITLE_COLUMN = "Задача"


class LinkFileError(Exception):
    """Файл не разобрать: нет нужных колонок, пустой, не та кодировка."""


# --- предположения для ненайденных -----------------------------------------
#
# Точного совпадения нет, но артикул почти наверняка тот же, просто записан
# иначе: «2N7002KTB_R1» в задаче против «2N7002KTB» в библиотеке — суффикс
# катушки, а деталь одна. Ниже — подбор похожего, чтобы человек не искал
# такие пары руками.

# сколько предположений показывать на одну ненайденную строку
SUGGEST_LIMIT = 3

# ниже этой похожести предлагать бессмысленно — будет шум
SUGGEST_THRESHOLD = 0.75

# по скольким первым символам артикулы группируются для сравнения:
# перебирать всю библиотеку на каждую строку слишком дорого
BUCKET_SIZE = 4

# потолок полных сравнений на один кусок названия. В библиотеке бывают
# тысячи артикулов с общим началом; без потолка подбор для одной строки
# занимал бы полсекунды, а для всего файла — минуты
MAX_COMPARISONS = 400

# с такой оценкой предположение считается уверенным: дальше не ищем
CONFIDENT = 0.9

NOT_PN_CHARS = re.compile(r"[^A-Za-z0-9]+")


def _core(text):
    """Артикул без разделителей, в верхнем регистре: «2N7002K-7» → «2N7002K7».

    Разделители в артикулах ставят кто во что горазд, а деталь одна и та же.
    """
    return NOT_PN_CHARS.sub("", text or "").upper()


def build_suggest_index(index):
    """Готовит структуры для быстрого подбора похожего артикула.

    ``by_core`` — артикулы без разделителей: по нему два самых надёжных
    правила (та же запись и лишний суффикс в задаче) находятся поиском по
    словарю, без перебора.

    ``buckets`` — те же артикулы, разложенные по первым символам; по ним
    идёт только нестрогое сравнение, которому словарь не поможет. Перебор
    внутри корзины ограничен: в библиотеке бывают тысячи артикулов с общим
    началом (типовые резисторы), и сравнивать строку с каждым — это
    полминуты на строку вместо миллисекунд.
    """
    by_core, buckets = {}, {}
    for source in index:
        for key, entry in source.items():
            core = _core(key)
            if len(core) < BUCKET_SIZE:
                continue
            by_core.setdefault(core, []).append((key, entry))
            buckets.setdefault(core[:BUCKET_SIZE], []).append((key, entry, core))
    return {"by_core": by_core, "buckets": buckets}


def _score(candidate_core, key_core):
    """Насколько артикул из библиотеки похож на кусок названия задачи.

    Порядок правил — по убыванию доверия: одинаковая запись без
    разделителей надёжнее общего начала, а общее начало надёжнее просто
    похожих строк.
    """
    if candidate_core == key_core:
        return 1.0, "запись отличается только разделителями"
    if candidate_core.startswith(key_core):
        # «2N7002KTB_R1» против «2N7002KTB»: в задаче лишний суффикс
        return 0.95, "в задаче лишний суффикс"
    if key_core.startswith(candidate_core):
        return 0.9, "в библиотеке артикул длиннее"
    return 0.0, ""


def _exact_and_prefix(core, by_core):
    """Правила, которые находятся поиском по словарю, а не перебором.

    Совпадение без разделителей — один поиск. «В задаче лишний суффикс» —
    по одному поиску на каждую длину начала, то есть десяток-другой, а не
    проход по всей библиотеке.
    """
    found = []
    for length in range(len(core), BUCKET_SIZE - 1, -1):
        for key, entry in by_core.get(core[:length], ()):
            score, reason = _score(core, _core(key))
            if score:
                found.append((key, entry, score, reason))
    return found


def _fuzzy(core, bucket, seen):
    """Нестрогое сравнение внутри корзины — самая дорогая часть.

    Дешёвые оценки difflib отсекают заведомо непохожее, не считая полного
    сравнения: ``real_quick_ratio`` смотрит только на длины, ``quick_ratio``
    — на общий набор символов. Обе дают оценку сверху, поэтому отбрасывать
    по ним безопасно. Число полных сравнений сверху ограничено.
    """
    matcher = SequenceMatcher()
    matcher.set_seq2(core)

    found, compared = [], 0
    for key, entry, key_core in bucket:
        if key in seen:
            continue
        matcher.set_seq1(key_core)
        if (matcher.real_quick_ratio() < SUGGEST_THRESHOLD
                or matcher.quick_ratio() < SUGGEST_THRESHOLD):
            continue
        if compared >= MAX_COMPARISONS:
            break
        compared += 1
        score = matcher.ratio()
        if score >= SUGGEST_THRESHOLD:
            found.append((key, entry, score, "похожий артикул"))
    return found


def suggest(text, prepared, limit=SUGGEST_LIMIT):
    """Что это мог быть за компонент, если точного совпадения не нашлось.

    Возвращает список ``{"pn", "targets", "score", "reason", "piece", "url"}``,
    самые правдоподобные впереди. Пустой список — если и похожего нет.
    """
    by_core = prepared["by_core"]
    buckets = prepared["buckets"]

    seen, found = set(), []
    for piece in candidates(text):
        core = _core(piece)
        if len(core) < BUCKET_SIZE:
            continue

        hits = _exact_and_prefix(core, by_core)
        # нестрогое сравнение дорогое, и считать его незачем, если словарь
        # уже дал уверенный ответ: «2N7002KTB_R1» → «2N7002KTB» найдено
        # точно, перебирать похожее сверх этого нечего
        if not hits:
            hits = _fuzzy(core, buckets.get(core[:BUCKET_SIZE], ()), seen)

        for key, entry, score, reason in hits:
            if key in seen:
                continue
            seen.add(key)
            targets = list(entry["targets"])
            table, pk = targets[0]
            found.append({"pn": entry["pn"], "targets": targets,
                          "score": score, "reason": reason, "piece": piece,
                          # ссылка на первую из записей: артикул один,
                          # и с его карточки видно остальные
                          "url": component_url(table, pk),
                          # таблица и ключ отдельно — по ним кнопка
                          # «Добавить» заводит ссылку на эту запись
                          "table": table,
                          "pk": pk})

        # уверенное совпадение найдено — остальные куски названия
        # разбирать не нужно, они дадут только шум
        if any(item["score"] >= CONFIDENT for item in found):
            break

    # длинный кусок названия надёжнее короткого, поэтому при равной
    # похожести побеждает совпадение по более длинному артикулу
    found.sort(key=lambda item: (-item["score"], -len(item["pn"])))
    return found[:limit]


def read_rows(source):
    """Читает CSV: путь, открытый файл или загруженный через форму.

    Колонки ищутся по заголовку, а не по номеру — в выгрузке их порядок
    может отличаться. utf-8-sig: такие файлы открывают в Excel, и BOM в
    начале обычен.
    """
    if hasattr(source, "read"):
        raw = source.read()
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                # выгрузка из Windows-программы бывает в cp1251
                try:
                    raw = raw.decode("cp1251")
                except UnicodeDecodeError as exc:
                    raise LinkFileError(
                        "Не удалось прочитать файл: неизвестная кодировка. "
                        "Сохраните его в UTF-8.") from exc
        handle = io.StringIO(raw)
    else:
        handle = open(source, encoding="utf-8-sig", newline="")

    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise LinkFileError("Файл пуст.")

        names = {name.strip(): name for name in reader.fieldnames if name}
        url_key = names.get(URL_COLUMN)
        title_key = names.get(TITLE_COLUMN)
        if not url_key or not title_key:
            raise LinkFileError(
                f"Нужны колонки «{URL_COLUMN}» и «{TITLE_COLUMN}», "
                f"а в файле: {', '.join(n for n in reader.fieldnames if n)}")

        rows = []
        for row in reader:
            url = (row.get(url_key) or "").strip()
            title = (row.get(title_key) or "").strip()
            if url and title:
                rows.append({"url": url, "title": title})
        if not rows:
            raise LinkFileError("В файле нет ни одной заполненной строки.")
        return rows


def _existing_links(rows):
    """Что из этого файла уже проставлено. Возвращает (пары, адреса).

    Пары — ``(адрес, таблица, ключ)``: по ним видно, что у конкретной
    записи стоит именно эта ссылка. Адреса — просто множество: по ним
    видно, что задачу уже разобрали, пусть даже вручную через кнопку
    «Добавить» рядом с предположением.

    Ищем по самим таблицам компонентов: колонка «Tracker URL» теперь там,
    отдельной таблицы со ссылками больше нет.
    """
    urls = {row["url"] for row in rows}
    if not urls:
        return set(), set()

    pairs = set()
    for category in CATEGORIES.values():
        if "tracker_url" not in category.field_names:
            continue
        with unavailable(category.table):
            found = (category.model.objects
                     .filter(tracker_url__in=urls)
                     .order_by()
                     .values_list("tracker_url", "id"))
            pairs |= {(url, category.table, pk) for url, pk in found}

    return pairs, {url for url, _, _ in pairs}


def resolve_rows(rows, index=None, skip_existing=True):
    """Делит строки на сопоставленные, ненайденные и уже заведённые.

    Возвращает (сопоставленные, ненайденные, уже заведённые). У
    сопоставленных добавлены ``targets`` (куда ссылку вешать), ``pn``
    (какой кусок названия совпал) и ``rule`` (по какому правилу).

    Повторная загрузка того же файла не должна показывать заново то, что
    уже разобрали: иначе после первого импорта список остаётся таким же
    длинным, и понять, что осталось сделать, невозможно. Строка считается
    заведённой, если ссылка уже стоит на всех найденных записях, а для
    ненайденных — если этот адрес вообще где-то есть: значит, его
    подтвердили кнопкой рядом с предположением.
    """
    index = index or build_index()
    pairs, urls = _existing_links(rows) if skip_existing else (set(), set())

    matched, unmatched, already = [], [], []
    for row in rows:
        targets, piece, rule = match(row["title"], index)
        if targets:
            done = all((row["url"], table, pk) in pairs for table, pk in targets)
            item = {**row, "targets": targets, "pn": piece, "rule": rule}
            (already if done else matched).append(item)
        elif row["url"] in urls:
            already.append(dict(row))
        else:
            unmatched.append(row)

    # корзины строятся один раз и только если есть для чего
    if unmatched:
        buckets = build_suggest_index(index)
        for row in unmatched:
            row["hints"] = suggest(row["title"], buckets)

    return matched, unmatched, already


def save_links(matched, source=""):
    """Проставляет ссылки компонентам. Возвращает (заполнено, заменено).

    «Заполнено» — колонка была пустой, «заменено» — там стояла другая
    ссылка. Разделение нужно, чтобы после импорта было видно, тронул ли он
    то, что кто-то завёл руками: колонка одна, и новая ссылка вытесняет
    старую, а не добавляется рядом, как было с отдельной таблицей.

    Совпадение адреса изменением не считается — повторный импорт того же
    файла не должен выглядеть как правка всей библиотеки.
    """
    filled = replaced = 0
    with transaction.atomic():
        for item in matched:
            for table, pk in item["targets"]:
                # Здесь запись читается напрямую, а не через refs.resolve:
                # мы внутри atomic(), а resolve гасит DatabaseError. Внутри
                # транзакции это не помощь, а вред — после отказа она уже
                # помечена к откату, и следующий запрос всё равно упадёт,
                # только уже непонятно почему.
                category = category_by_table(table)
                if category is None or "tracker_url" not in category.field_names:
                    continue
                obj = category.model.objects.filter(pk=pk).first()
                if obj is None:
                    # запись удалили, пока разбирали файл
                    continue
                current = usable(obj.tracker_url)
                if current == item["url"]:
                    continue
                obj.tracker_url = item["url"]
                obj.save(update_fields=["tracker_url"])
                if current:
                    replaced += 1
                else:
                    filled += 1
    return filled, replaced
