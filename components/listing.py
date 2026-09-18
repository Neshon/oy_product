"""Всё, что нужно списку компонентов: группа, фильтры, сортировка, страница.

Раньше эти помощники лежали в ``components.views`` вперемешку с самими
представлениями. Здесь они собраны вместе: страница со списком — самая
сложная в проекте, и правила, по которым она строится, удобнее держать
отдельно от того, что она отдаёт в шаблон.
"""

from django.http import Http404
from django.shortcuts import get_object_or_404

from .cache import FILTERS_KEY, cached
from .db import fallback
from .options import table_options
from .querystring import VALUE_SEPARATOR, values_of
from .registry import get_category

PAGE_SIZES = (25, 50, 100, 200)
DEFAULT_PAGE_SIZE = 25
MAX_FILTER_CHOICES = 300
NUMERIC_PK = ("AutoField", "BigAutoField", "IntegerField")


def category_or_404(slug):
    category = get_category(slug)
    if category is None:
        raise Http404(f"Группа компонентов «{slug}» не найдена")
    return category


def fetch(category, pk):
    """Достаёт запись по ключу; нечисловой ключ у числового PK — это 404, не 500."""
    if category.model._meta.pk.get_internal_type() in NUMERIC_PK:
        try:
            pk = int(pk)
        except (TypeError, ValueError):
            raise Http404("Некорректный идентификатор записи")
    return get_object_or_404(category.model, pk=pk)


def filter_choices(category, params=None):
    """Значения фильтров этой группы — из справочника или из самой таблицы.

    Фильтры сужают друг друга: когда выбран производитель, в остальных
    списках остаются только значения, которые у его компонентов вообще
    встречаются. Свои значения фильтр при этом не учитывает — иначе,
    выбрав одно, второе к нему уже было бы не добавить.

    Каждое значение, которого нет в справочнике, — это ``SELECT DISTINCT``
    по столбцу, то есть у резисторов восемь проходов по таблице на каждое
    открытие списка. Пока ничего не выбрано, ответ один и тот же для всех,
    поэтому он кэшируется: правка через сайт сбрасывает кэш сразу,
    изменения мимо нас подхватятся по истечении срока (см.
    ``components.cache``). Суженные списки не кэшируются: сочетаний
    фильтров слишком много, чтобы их запоминать, а сбрасывать пришлось бы
    все сразу. Считаются они по уже отобранным записям, то есть по
    заведомо меньшей выборке, чем полная таблица.
    """
    chosen = _chosen(params, category)
    if not chosen:
        return cached(FILTERS_KEY.format(table=category.table),
                      lambda: _filter_choices(category))
    return _filter_choices(category, chosen)


def _chosen(params, category):
    """Что уже выбрано в фильтрах: ``{имя поля: "знач1|знач2"}``."""
    if params is None:
        return {}
    chosen = {}
    for name in category.filter_fields:
        values = values_of(params, name)
        if values:
            chosen[name] = VALUE_SEPARATOR.join(values)
    return chosen


def _filter_choices(category, chosen=None):
    options = table_options(category.table)
    chosen = chosen or {}
    filters = []
    for name, label in category.filters:
        # для самого фильтра его же значения не учитываем
        others = {key: value for key, value in chosen.items() if key != name}
        values = _values(category, name, options.get(name), others)
        if values:
            filters.append((name, str(label), values))
    return filters


@fallback(list, "значения фильтра над списком")
def _values(category, name, from_options, others):
    """Значения одного фильтра с учётом того, что выбрано в остальных.

    Недоступная таблица — это список без этого фильтра, но страница
    откроется.
    """
    if from_options is not None and not others:
        # поле есть в справочнике: список задаётся в админке, а не
        # собирается по факту из данных
        return list(from_options)

    queryset = category.model.objects.all()
    if others:
        queryset = queryset.apply_filters(others, category.filter_fields)
    found = list(queryset.exclude(**{f"{name}__isnull": True})
                 .exclude(**{name: ""})
                 .order_by(name)
                 .values_list(name, flat=True)
                 .distinct()[:MAX_FILTER_CHOICES])

    if from_options is None:
        return found
    # справочник задаёт и состав, и порядок; сужение только убирает из него
    # то, чего в отобранных записях нет
    present = set(found)
    return [value for value in from_options if value in present]


def sorted_queryset(queryset, category, request):
    """Применяет сортировку из строки запроса, если столбец такой есть."""
    sort = request.GET.get("sort") or ""
    direction = request.GET.get("dir", "asc")
    if sort in category.field_names:
        order = f"-{sort}" if direction == "desc" else sort
        return queryset.order_by(order), sort, direction
    return queryset, "", direction


def page_size(request):
    try:
        size = int(request.GET.get("per_page", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE
