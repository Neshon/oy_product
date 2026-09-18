"""Где компонент используется на платах.

Основной путь — ссылка, проставленная при импорте: у строки состава
хранится таблица и ключ найденной записи. Для составов, загруженных до
появления ссылок, остаётся запасной поиск по GBT P/N и паре
Vendor P/N + Vendor.
"""

from django.db.models import F, Q

from components.db import fallback
from components.matching import usable

from .models import BoardItem
from .references import normalize_references, split_references

USAGE_LIMIT = 100


@fallback(lambda: ([], ""), "платы, где применён компонент")
def find_usages(component, table, limit=USAGE_LIMIT, current_only=True):
    """Платы, на которых стоит этот компонент — по одной записи на плату.

    Возвращает (список плат, чем сопоставлено). У каждой платы собраны
    обозначения позиций, суммарное количество и число позиций; сами строки
    состава наружу не отдаются — в карточке они не нужны.
    """
    items = BoardItem.objects.filter(component_table=table,
                                     component_id=component.pk)
    matched_by = "связи из импорта"

    if not items.exists():
        items, matched_by = _fallback(component)
        if items is None:
            return [], ""

    if current_only:
        # интересует текущий состав, а не то, что было в старых ревизиях
        items = items.filter(revision__board__current_revision=F("revision"))

    items = list(items.select_related("revision__board")[:limit])
    _fill_position_data(items)
    return group_by_board(items), (matched_by if items else "")


def _fallback(component):
    """Поиск по артикулам — для составов, импортированных без ссылок."""
    gbt_pn = usable(getattr(component, "gbt_pn", ""))
    vendor_pn = usable(getattr(component, "vendor_pn", ""))
    vendor = usable(getattr(component, "vendor", ""))

    if gbt_pn:
        found = BoardItem.objects.filter(component_id__isnull=True,
                                         gbt_pn__iexact=gbt_pn)
        if found.exists():
            return found, "GBT P/N"

    if vendor_pn and vendor:
        found = BoardItem.objects.filter(
            Q(component_id__isnull=True) & Q(vendor_pn__iexact=vendor_pn)
            & Q(vendor__iexact=vendor))
        if found.exists():
            return found, "Vendor P/N и Vendor"

    return None, ""


def _fill_position_data(items):
    """Проставляет количество и обозначения позиции строкам замен.

    В BOM QTY и Part References стоят только у основной строки, у замен эти
    ячейки пустые. Для вопросов «сколько их на плате» и «где именно» нужны
    данные позиции, поэтому берём их у основной строки той же позиции.
    """
    for item in items:
        item.position_qty = item.qty
        item.position_references = item.references

    orphans = [i for i in items
               if i.position is not None
               and (i.qty is None or not i.references)]
    if not orphans:
        return

    keys = {(i.revision_id, i.position) for i in orphans}
    mains = (BoardItem.objects
             .filter(kind=BoardItem.MAIN,
                     revision_id__in={revision_id for revision_id, _ in keys},
                     position__in={position for _, position in keys})
             # из основной строки нужны только количество и обозначения:
             # описания и артикулы здесь не читаются
             .only("revision_id", "position", "qty", "references")
             .order_by())
    by_key = {(m.revision_id, m.position): m for m in mains}

    for item in orphans:
        main = by_key.get((item.revision_id, item.position))
        if not main:
            continue
        if item.position_qty is None:
            item.position_qty = main.qty
        if not item.position_references:
            item.position_references = main.references


def group_by_board(items):
    """Схлопывает строки состава в одну запись на плату.

    Один и тот же компонент нередко стоит на плате в нескольких позициях —
    в карточке это выглядело как несколько одинаковых строк подряд. Здесь
    они собираются в одну: обозначения объединяются, количество
    суммируется, число позиций считается отдельно.

    Порядок плат сохраняется тот, в котором пришли строки.
    """
    boards = {}
    for item in items:
        board = item.revision.board
        entry = boards.setdefault(board.pk, {
            "board": board,
            "positions": 0,
            "qty": None,
            "references": [],
        })
        entry["positions"] += 1

        qty = getattr(item, "position_qty", None)
        if qty is not None:
            entry["qty"] = (entry["qty"] or 0) + qty

        for reference in split_references(
                getattr(item, "position_references", "")):
            # одно обозначение не должно попасть дважды, если компонент
            # найден и основной строкой, и её заменой
            if reference not in entry["references"]:
                entry["references"].append(reference)

    for entry in boards.values():
        entry["references"] = normalize_references(
            ", ".join(entry["references"]))
    return list(boards.values())


@fallback(lambda: ([], 0), "где применён компонент, все ревизии")
def usage_summary(component, table):
    """Где компонент стоит — по всем ревизиям, а не только по текущим.

    Для удаления важна вся история: строка в старой ревизии тоже потеряет
    связь и превратится в данные из файла без ссылки на библиотеку.
    Возвращает (список плат, число строк).
    """
    items = (BoardItem.objects
             .filter(component_table=table, component_id=component.pk)
             .select_related("revision__board"))
    boards, rows = {}, 0
    for item in items:
        rows += 1
        revision = item.revision
        board = revision.board
        entry = boards.setdefault(board.pk, {
            "board": board, "revisions": [], "current": False})
        label = revision.oy_pn or revision.label
        if label not in entry["revisions"]:
            entry["revisions"].append(label)
        if board.current_revision_id == revision.pk:
            entry["current"] = True

    return sorted(boards.values(),
                  key=lambda entry: (not entry["current"],
                                     entry["board"].base_pn or "")), rows
