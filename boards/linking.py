"""Связывание строк BOM с записями в библиотеке компонентов.

Связь ставится двумя способами, и оба — один раз, при появлении строки.

Строки из файла сопоставляет импорт: артикул из BOM ищется в библиотеке, и
найденное — имя таблицы и первичный ключ — записывается в саму строку.
Сравнивать артикулы при каждом показе состава было бы и дорого, и хрупко:
регистр, пробелы, заглушки вроде «---». Индекс для этого строится одним
проходом по всем таблицам: 27 запросов на импорт вместо двух запросов на
каждую из сотен строк.

Строку, добавленную в состав человеком, сопоставлять не нужно вовсе:
компонент он выбрал сам, запись известна. Оттуда же берутся и поля строки —
:func:`component_values`.

Поиск под одну строку по введённому артикулу здесь когда-то был
(``find_component``). Он понадобился ручному вводу артикулов в состав, а
вместе с ним и убран: угадывать больше нечего.
"""

from components.matching import usable
from components.registry import scan

# порядок правил: сначала внутренний номер, затем артикул производителя
MATCH_GBT = "gbt"
MATCH_VENDOR = "vendor"
# А это правило не ищет ничего: компонент указал человек, выбрав его в
# библиотеке. Оно надёжнее двух предыдущих — сравнивать артикулы не надо,
# запись известна, — и по нему видно, что связь не угадана
MATCH_PICK = "pick"

# Поля строки состава, которые заполняются из карточки выбранного
# компонента. Список — это ровно те колонки BOM, которые есть и в
# библиотеке: количество, обозначения и комментарий берутся из платы, а не
# из компонента, и здесь их нет.
#
# Переносятся они один раз, при добавлении строки, и дальше живут своей
# жизнью: состав — документ, и правка описания в библиотеке не меняет уже
# выпущенный BOM. Что в библиотеке сейчас — видно по ссылке на карточку.
COPIED_FIELDS = ("vendor_pn", "vendor", "country", "oy_id", "oy_pn",
                 "gbt_pn", "group", "subgroup", "description", "smt_tht")


def component_values(obj):
    """Значения полей компонента в виде, годном для строки состава.

    ``None`` в библиотеке — обычное дело (колонки необязательные), а в
    строке состава поля не допускают ``NULL``: приводим к пустой строке
    здесь, а не в трёх местах вызова.
    """
    return {name: (getattr(obj, name, "") or "").strip()
            for name in COPIED_FIELDS}


def build_index():
    """Готовит два словаря: по GBT P/N и по паре Vendor P/N + Vendor."""
    by_gbt, by_vendor = {}, {}

    for category, values in scan(("id", "gbt_pn", "vendor_pn", "vendor")):
        target = (category.table, values["id"])

        gbt = usable(values.get("gbt_pn")).lower()
        if gbt:
            by_gbt.setdefault(gbt, target)

        vendor_pn = usable(values.get("vendor_pn")).lower()
        vendor = usable(values.get("vendor")).lower()
        if vendor_pn and vendor:
            by_vendor.setdefault((vendor_pn, vendor), target)

    return by_gbt, by_vendor


def resolve(item, index):
    """Возвращает (таблица, id, правило) для строки состава."""
    by_gbt, by_vendor = index

    gbt = usable(item.get("gbt_pn")).lower()
    if gbt and gbt in by_gbt:
        table, pk = by_gbt[gbt]
        return table, pk, MATCH_GBT

    vendor_pn = usable(item.get("vendor_pn")).lower()
    vendor = usable(item.get("vendor")).lower()
    if vendor_pn and vendor and (vendor_pn, vendor) in by_vendor:
        table, pk = by_vendor[(vendor_pn, vendor)]
        return table, pk, MATCH_VENDOR

    return "", None, ""


def link_items(items, index=None):
    """Проставляет ссылки на компоненты в разобранных строках BOM."""
    index = index or build_index()
    linked = 0
    for item in items:
        table, pk, match = resolve(item, index)
        item["component_table"] = table
        item["component_id"] = pk
        item["component_match"] = match
        linked += int(pk is not None)
    return linked
