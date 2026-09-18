"""Показатели по составам плат для главной страницы.

Считается только по текущим ревизиям: старые ревизии — история, и
несвязанные строки в них ни о чём не говорят.
"""

from django.db.models import Count, F, Q

from components.cache import COVERAGE_KEY, cached
from components.db import fallback

from .models import BoardItem

TOP_BOARDS = 5


def bom_coverage():
    """Насколько состав плат опирается на библиотеку, а не на текст из файла.

    Возвращает словарь с числами и списком плат, где несвязанных строк
    больше всего, либо None — если платы ещё не загружены или база
    недоступна.

    Показатель стоит двух запросов по всем строкам составов и висит на
    главной, поэтому кэшируется. Импорт BOM и правка состава сбрасывают
    его сразу — см. ``boards.apps``.
    """
    return cached(COVERAGE_KEY, _bom_coverage)


@fallback(None, "опора составов на библиотеку")
def _bom_coverage():
    """Тот же показатель, но всегда из базы. Два запроса: сводка и разрез."""
    current = BoardItem.objects.filter(
        revision__board__current_revision=F("revision"))

    totals = current.aggregate(
        rows=Count("id"),
        linked=Count("id", filter=Q(component_id__isnull=False)))

    rows = totals["rows"] or 0
    if not rows:
        return None

    # order_by() перед группировкой: иначе поля Meta.ordering у
    # BoardItem попали бы в GROUP BY и разрезали счётчик по позициям
    worst = list(current.filter(component_id__isnull=True)
                 .order_by()
                 .values("revision__board__id",
                         "revision__board__base_pn")
                 .annotate(unlinked=Count("id"))
                 .order_by("-unlinked")[:TOP_BOARDS])

    linked = totals["linked"] or 0
    return {
        "rows": rows,
        "linked": linked,
        "unlinked": rows - linked,
        "percent": round(linked * 100 / rows),
        "worst": [{"id": item["revision__board__id"],
                   "base_pn": item["revision__board__base_pn"],
                   "unlinked": item["unlinked"]} for item in worst],
    }
