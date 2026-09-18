"""Разбор BOM-файла Excel.

Файлы в природе встречаются как минимум в трёх видах:

1. «Parts:»-стиль — шапка парами «подпись → значение» (Actual OY BOM P/N и
   т.д.), таблица с колонками I/N или Item Number, M/S, Vendor P/N, GBT P/N,
   Part References, QTY;
2. «AVL LIST»-стиль — без шапки платы, вместо неё строка ``Model Name :
   XXXX``, таблица с колонками M/S, Vendor, Vendor P/N, MOBO Vendor P/N
   (аналог GBT P/N), QTY, Location (аналог обозначений);
3. плоский список без колонки M/S вообще — тогда каждая строка считается
   основной, замен не бывает.

Колонки ищутся по названию, а не по номеру, поэтому перестановка столбцов
не ломает разбор. Названия приводятся к общему виду: убираются регистр,
подчёркивания, префикс «Parts:», разница между «P/N» и «PN», а также
похожие на латиницу кириллические буквы, изредка попадающие в заголовки
при копировании между документами.

Если в файле нет ни явной шапки платы, ни строки ``Model Name``, номер
платы берётся из имени файла — иначе плату нечем было бы опознать.
"""

import datetime
import os
import re

from openpyxl import load_workbook

from components.matching import is_placeholder

from .references import normalize_references

SHEET_NAME = "BOM"
MAX_HEADER_SCAN = 40

# латиница-двойники кириллических букв: чинят заголовки вида «DeSсription»,
# где часть букв кириллическая, хотя выглядит как обычный текст
CYRILLIC_LOOKALIKES = str.maketrans({
    "а": "a", "с": "c", "е": "e", "о": "o", "р": "p", "у": "y", "х": "x",
    "А": "A", "С": "C", "Е": "E", "О": "O", "Р": "P", "У": "Y", "Х": "X",
    "В": "B", "К": "K", "М": "M", "Н": "H", "Т": "T",
})

# подпись в шапке платы → поле Board. Ключи уже в общем виде (см. _key)
HEADER_MAP = {
    "actual gct bom pn": "gct_pcb",
    "actual oy bom pn": "oy_pn",
    # «Old GCT BOM P/N» больше не разбираем: поля под него нет, им не
    # пользовались. Строка в присланном файле остаётся, мы её просто не
    # читаем — шапка сопоставляется по подписям, лишние не мешают.
    "old oy bom pn": "previous_revision",
    # Децимальный номер из файла — то же самое, что «Децимальный номер узла
    # печатного (PCBA)» в карточке, поэтому кладём его прямо туда. Заполнит
    # он карточку или нет, решает BomHeader.apply_header: пустое поле —
    # заполнит, заполненное — оставит как есть.
    "decimal number": "decimal_pcba",
    # «Date» и «Author» из файла больше не храним: на карточке эти две
    # строки теперь значат «когда и кто загрузил BOM», а что написано в
    # присланном файле, ни разу не пригодилось.
}

# заголовок колонки таблицы → поле строки состава. Ключи в общем виде:
# без регистра, без подчёркиваний и префикса «Parts:», «p/n» = «pn»
COLUMN_MAP = {
    "i/n": "position", "item number": "position", "item no": "position",
    "item": "position", "№": "position", "no": "position",

    "m/s": "kind", "ms": "kind", "selector": "kind",
    "main/second source": "kind",

    "vendor pn": "vendor_pn",
    "vendor": "vendor",
    "country": "country",
    "oy id": "oy_id",
    "oy pn": "oy_pn",
    "gbt pn": "gbt_pn", "mobo vendor pn": "gbt_pn", "gigabyte pn": "gbt_pn",
    "group": "group", "group gr": "group",
    "subgroup": "subgroup",
    "description": "description",
    "description gbt": "description_gbt",
    "smt/tht": "smt_tht", "smt tht": "smt_tht",
    "part references": "references", "part reference": "references",
    "references": "references", "location": "references",
    "designator": "references", "designators": "references",
    "qty": "qty", "quantity": "qty", "q/y": "qty",
    "quantity for 1": "qty", "qty for 1": "qty",
    "comment": "comment", "notice": "comment",
}

# Поля строки состава, которые просто читаются из своей колонки. Тип строки
# и номер позиции сюда не входят: они разбираются отдельно — по ним строка
# и опознаётся. Список постоянный, поэтому считается один раз, а не на
# каждую из сотен строк файла.
ITEM_FIELDS = tuple(name for name in dict.fromkeys(COLUMN_MAP.values())
                    if name not in ("kind", "position"))

# итоговые строки под таблицей: не компонент, а сумма по листу
FOOTER_MARKERS = {"итого", "total", "общая цена", "summary", "сумма", "всего"}

DATE_FORMAT = "%d.%m.%Y"
# три числа через точку, дефис, косую черту или пробел
DATE_PARTS_RE = re.compile(r"(\d{1,4})[.\-/\s](\d{1,2})[.\-/\s](\d{1,4})")

MODEL_NAME_RE = re.compile(r"model\s*name\s*:\s*(.+)", re.I)
BOM_SUFFIX_RE = re.compile(r"[\s_-]*bom$", re.I)


class BomParseError(Exception):
    """Файл не похож на BOM или в нём нет обязательных данных."""


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _key(value):
    """Приводит подпись колонки или подписи в шапке к общему виду."""
    text = _text(value).translate(CYRILLIC_LOOKALIKES)
    text = text.replace("\xa0", " ").replace("_", " ")
    text = re.sub(r"\s+", " ", text).lower()
    text = re.sub(r"^parts\s*:\s*", "", text)
    return text.replace("p/n", "pn").strip()


def _to_int(value):
    text = _text(value)
    if not text:
        return None
    match = re.search(r"-?\d+", text.replace(" ", ""))
    return int(match.group()) if match else None


def normalize_date(value):
    """Приводит дату BOM к виду ДД.ММ.ГГГГ.

    В файлах встречается и «12.11.2025», и «2025.09.30»; Excel иногда
    отдаёт настоящую дату вместо строки. Что разобрать не удалось —
    возвращается как есть: терять исходное значение хуже, чем показать
    его в чужом формате.

    Разбор шапки этим больше не пользуется: даты из присланного файла мы не
    храним. Функция осталась ради миграции 0003_normalize_dates — она чинит
    даты, записанные до появления правила, и обязана работать при
    накатывании миграций с нуля, на пустой базе.
    """
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime(DATE_FORMAT)

    text = _text(value)
    if not text:
        return ""

    match = DATE_PARTS_RE.search(text)
    if not match:
        return text

    first, second, third = (int(part) for part in match.groups())

    if first > 31:                       # 2025.09.30 — год впереди
        year, month, day = first, second, third
    else:
        day, month, year = first, second, third
        if month > 12 and day <= 12:     # 09/30/2025 — американский порядок
            day, month = month, day

    if year < 100:                       # 20.05.25 — двузначный год
        year += 2000

    try:
        return datetime.date(year, month, day).strftime(DATE_FORMAT)
    except ValueError:
        return text                      # 31.02.2025 и подобное — не трогаем


def _filename_of(source):
    name = getattr(source, "name", None)
    if not name and isinstance(source, str):
        name = source
    return os.path.basename(name or "")


def _fallback_board_name(filename):
    """Если в файле нет ни шапки, ни Model Name — берём имя файла."""
    stem = re.sub(r"\.xlsx?$", "", filename, flags=re.I)
    stem = BOM_SUFFIX_RE.sub("", stem)
    return stem.strip(" _-") or "BOM"


def parse_bom(source):
    """Разбирает файл и возвращает (данные платы, список строк состава)."""
    try:
        workbook = load_workbook(source, data_only=True, read_only=True)
    except Exception as exc:  # openpyxl бросает разные типы на битых файлах
        raise BomParseError(f"Не удалось открыть файл: {exc}") from exc

    sheet = workbook[SHEET_NAME] if SHEET_NAME in workbook.sheetnames \
        else workbook.worksheets[0]

    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    if not rows:
        raise BomParseError("Лист пустой")

    header_row, has_kind = _find_header_row(rows)
    columns = _map_columns(rows[header_row])
    board = _read_board_header(rows[:header_row])
    items = _read_items(rows[header_row + 1:], columns, has_kind,
                        header_row + 2)

    if not board.get("oy_pn"):
        model_name = _find_model_name(rows[:header_row + 1])
        board["oy_pn"] = model_name or _fallback_board_name(_filename_of(source))

    if not items:
        raise BomParseError("В файле нет ни одной строки состава")

    return board, items


def _row_columns(row):
    """Какие поля узнаются в строке — для поиска заголовка и его состава."""
    return {COLUMN_MAP[key] for cell in row
            if (key := _key(cell)) in COLUMN_MAP}


def _find_header_row(rows):
    """Ищет строку заголовков по составу колонок, а не по одной из них.

    Сначала строка с M/S и артикулом — это основной, самый частый случай.
    Если такой во всём листе нет, подходит строка без M/S, но с артикулом
    и описанием или подгруппой: тогда таблица плоская, все строки основные.
    """
    fallback = None
    for index, row in enumerate(rows[:MAX_HEADER_SCAN]):
        found = _row_columns(row)
        has_part = "vendor_pn" in found or "gbt_pn" in found
        if not has_part:
            continue
        if "kind" in found:
            return index, True
        if fallback is None and ("description" in found or "subgroup" in found
                                 or "country" in found):
            fallback = index

    if fallback is not None:
        return fallback, False

    raise BomParseError(
        "Не найдена строка заголовков: должны быть колонки вида "
        "«Vendor PN» или «GBT PN», а также «M/S»")


def _map_columns(header):
    columns = {}
    for index, cell in enumerate(header):
        field = COLUMN_MAP.get(_key(cell))
        # первое вхождение выигрывает: «Description» встречается раньше,
        # чем «Description GBT», и перепутать их нельзя
        if field and field not in columns:
            columns[field] = index
    if "vendor_pn" not in columns and "gbt_pn" not in columns:
        raise BomParseError(
            "В таблице нет ни «Vendor PN», ни «GBT PN» — "
            "строки состава не с чем сопоставить")
    return columns


def _read_board_header(rows):
    """Ищет пары «подпись — значение»: значение стоит правее подписи."""
    board = {}
    for row in rows:
        cells = [(index, _text(cell)) for index, cell in enumerate(row)]
        for index, cell in cells:
            field = HEADER_MAP.get(_key(cell))
            if not field:
                continue
            value = next((text for position, text in cells
                          if position > index and text), "")
            if value:
                board[field] = value
    return board


def _find_model_name(rows):
    """Запасной источник номера платы: строка «Model Name : XXXX»."""
    for row in rows:
        for cell in row:
            text = _text(cell)
            match = text and MODEL_NAME_RE.search(text)
            if match and match.group(1).strip():
                return match.group(1).strip()
    return ""


def _cell_of(value, field):
    """Значение ячейки в том виде, в каком оно ляжет в строку состава.

    Количество должно остаться числом, а обозначения позиций приводятся к
    запятым прямо здесь: разделитель в приходящих файлах бывает какой
    угодно, и незачем разбираться с этим при каждом показе и выгрузке.
    """
    if field == "qty":
        return _to_int(value)
    if field == "references":
        return normalize_references(_text(value))
    return _text(value)


def _cell(row, columns, field):
    """Ячейка строки по имени поля; None, если колонки нет или строка короче."""
    index = columns.get(field)
    if index is None or index >= len(row):
        return None
    return row[index]


def _is_not_a_component(row, columns):
    """Строка-итог или строка без артикулов — в состав не идёт.

    Нужно там, где своей колонки M/S нет: в таблице с M/S пустые строки и
    итоги отсеиваются сами, у них не проставлен тип.
    """
    vendor_pn = _text(_cell(row, columns, "vendor_pn"))
    gbt_pn = _text(_cell(row, columns, "gbt_pn"))
    if vendor_pn.lower() in FOOTER_MARKERS or gbt_pn.lower() in FOOTER_MARKERS:
        return True
    return ((not vendor_pn or is_placeholder(vendor_pn))
            and (not gbt_pn or is_placeholder(gbt_pn)))


def _read_items(rows, columns, has_kind, first_row_number):
    items = []
    position = None

    for offset, row in enumerate(rows):
        if has_kind:
            kind = _text(_cell(row, columns, "kind")).upper()[:1]
            if kind not in ("M", "S"):
                continue  # пустые строки и итоги пропускаем
        else:
            # таблица плоская: своей колонки M/S нет, каждая заполненная
            # строка — основная
            if _is_not_a_component(row, columns):
                continue
            kind = "M"

        # у замены своего номера позиции нет — она идёт под номером
        # последней основной строки
        if kind == "M":
            position = (_to_int(_cell(row, columns, "position"))
                        or ((position or 0) + 1))

        item = {"kind": kind, "position": position,
                "row": first_row_number + offset}
        for field in ITEM_FIELDS:
            item[field] = _cell_of(_cell(row, columns, field), field)
        items.append(item)

    return items
