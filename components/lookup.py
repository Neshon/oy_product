"""Поиск компонента по всем таблицам библиотеки сразу.

Спрашивают об этом из двух мест, и вопрос у них один: «где во всех 27
таблицах встречается такая строка». Отличается только то, что делают с
ответом — глобальный поиск показывает его по группам и ведёт на карточки,
а выбор компонента в состав платы (:mod:`boards.views`) собирает из него
один список, из которого человек тычет в нужную строку.

Обход тут один на оба случая. Таблиц много, и каждая из них — отдельный
запрос: писать этот обход дважды значило бы однажды получить два разных
поиска, которые на один и тот же запрос отвечают по-разному.

Недоступная таблица не роняет поиск: она просто не даёт совпадений
(см. :mod:`components.db`).
"""

from .db import unavailable
from .registry import MAIN_CATEGORIES, REPLACEMENT_CATEGORIES


def searchable():
    """Где ищем: сначала рабочие группы, за ними таблицы замен."""
    return MAIN_CATEGORIES + REPLACEMENT_CATEGORIES


def matches(term, limit, categories=None):
    """Совпадения по каждой таблице: ``[(категория, выборка, записи, ещё)]``.

    ``выборка`` — незавершённый queryset: по нему считают точное число, если
    оно зачем-то нужно. ``ещё`` — признак того, что совпадений больше, чем
    показано: берётся на одну запись сверх лимита, и по её наличию всё
    видно без ``COUNT`` по каждой из 27 таблиц.

    Пустой запрос — пустой ответ, а не вся библиотека: показывать «все
    компоненты» по несуществующему запросу незачем, а стоит это полного
    обхода.
    """
    term = (term or "").strip()
    if not term:
        return []

    found = []
    for category in (searchable() if categories is None else categories):
        rows, queryset = [], None
        with unavailable(category.table):
            queryset = category.model.objects.search(term)
            rows = list(queryset[:limit + 1])
        if rows:
            found.append((category, queryset, rows[:limit], len(rows) > limit))
    return found


def flat(term, limit, categories=None):
    """Плоский список ``[(категория, запись)]`` и признак «показано не всё».

    Для выбора компонента: человеку, который ищет конкретный артикул, нужен
    один список, а не два десятка табличек по группам — он и сам не знает
    заранее, конденсатор это или микросхема.

    Порядок: рабочие группы раньше замен, внутри — по названию группы и
    артикулу. Общий лимит режет уже собранный список, поэтому при переборе
    он же берётся и на таблицу: больше, чем поместится, читать неоткуда.
    """
    rows, more = [], False
    for category, _queryset, objects, has_more in matches(term, limit,
                                                          categories):
        rows += [(category, obj) for obj in objects]
        more = more or has_more

    rows.sort(key=lambda row: (row[0].replacement, row[0].title,
                               (row[1].vendor_pn or "").lower()))
    return rows[:limit], more or len(rows) > limit
