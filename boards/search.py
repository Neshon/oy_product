"""Платы и их составы в глобальном поиске."""

from django.db.models import Q

from components.db import fallback

from .models import Board, BoardItem
from .pn import canonical

LIMIT = 10

# Поля ревизии, по которым ищут плату. Имена сверяются с моделью тестом
# RevisionSearchFieldsTests: удалённое поле иначе обнаруживается только
# отказом всей страницы поиска у пользователя.
REVISION_SEARCH_FIELDS = (
    "oy_pn", "gct_pcb", "gct_bom", "previous_revision", "decimal_pcba",
)


def revision_match(term):
    """Условие «у платы есть ревизия, подходящая под запрос».

    Одно на два места: реестр плат и глобальный поиск. Когда условие было
    выписано в каждом своими руками, удаление поля чинилось в одном месте
    и оставалось в другом — и вылезало отказом страницы у пользователя.
    """
    condition = Q()
    for name in REVISION_SEARCH_FIELDS:
        condition |= Q(**{f"revisions__{name}__icontains": term})
    return condition


def _boards_matching(term):
    """Queryset плат: номер и наименование свои, остальное — у ревизий.

    Номера GCT и децимальные хранит ревизия, поэтому ищем их через неё:
    найденной всё равно должна оказаться плата — искавший набрал номер, а
    не выбирал уровень.

    Условие по ревизиям собирает revision_match — оно же стоит в фильтре
    реестра плат.
    """
    return Board.objects.filter(
        Q(base_pn__icontains=term) | Q(base_pn__icontains=canonical(term))
        | Q(name__icontains=term)
        | revision_match(term)).distinct()


def _items_matching(term):
    """Queryset строк составов: артикулы, описание, обозначения на плате."""
    return (BoardItem.objects
            .filter(Q(vendor_pn__icontains=term) | Q(vendor__icontains=term)
                    | Q(gbt_pn__icontains=term) | Q(oy_id__icontains=term)
                    | Q(oy_pn__icontains=term)
                    | Q(description__icontains=term)
                    | Q(references__icontains=term))
            .select_related("revision__board"))


@fallback(lambda: ([], 0), "превью глобального поиска по платам")
def _preview(matching, term, limit):
    """Первые ``limit`` записей и сколько их всего.

    Недоступная база — пустая карточка, а не ошибка на всей странице
    поиска: рядом стоят карточки по таблицам компонентов, и они своё
    покажут.
    """
    found = matching(term)
    return list(found[:limit]), found.count()


def search_boards(term, limit=LIMIT):
    """Превью для карточки глобального поиска: платы."""
    return _preview(_boards_matching, term, limit)


def search_items(term, limit=LIMIT):
    """Превью для карточки глобального поиска: строки составов."""
    return _preview(_items_matching, term, limit)


@fallback(lambda: BoardItem.objects.none(), "поиск по составам плат")
def items_queryset(term):
    """Queryset совпадений без выборки в память — для постраничного показа.

    В отличие от ``search_items``, ничего не читает из базы сразу: Paginator
    сам добавит LIMIT/OFFSET, когда запросит конкретную страницу. Так полный
    список (boards:item-search) не грузит в память все найденные строки
    разом, если их тысячи.
    """
    return _items_matching(term)
