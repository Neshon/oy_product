"""Кэш дорогих выборок по таблицам компонентов.

Некоторые вопросы к базе стоят полного просмотра таблицы, а ответ на них
меняется редко:

* значения фильтров над списком — ``SELECT DISTINCT`` по каждому из восьми
  фильтруемых столбцов, то есть восемь проходов по таблице на каждое
  открытие страницы;
* значения по умолчанию для новой записи — группировка по столбцу;
* счётчики на главной — ``COUNT(*)`` по четырнадцати таблицам;
* справочник выпадающих списков — два запроса на каждую форму и на каждый
  набор фильтров.

Всё это кладётся сюда. Правки, сделанные через сам сайт, сбрасывают кэш
сразу (см. сигналы в ``components.apps``), а изменения, пришедшие в базу
мимо нас — сторонним софтом или руками в psql, — подхватятся не позже, чем
через ``COMPONENTS_CACHE_SECONDS``. Ноль в этой настройке выключает кэш
целиком: удобно, когда данные правят снаружи и видеть их надо сразу.

Кэш по умолчанию локальный для процесса (LocMemCache). Если рабочих
процессов несколько, у каждого он свой — на корректность это не влияет,
сброс просто доходит до остальных по истечении срока. Общий кэш (Redis)
включается настройкой ``DJANGO_CACHE_URL``.

Кэш здесь — ускорение, а не часть работы приложения: если он недоступен
(упал Redis, кончилась память), значение просто считается заново, а в
журнал уходит предупреждение. Ронять из-за этого страницу нельзя.
"""

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_SECONDS = 300

# значения фильтров над списком группы
FILTERS_KEY = "components:filters:{table}"
# счётчики записей для главной страницы
COUNTS_KEY = "components:counts"
# справочник выпадающих списков для таблицы
OPTIONS_KEY = "components:options:{table}"
# значения, подставляемые в форму нового компонента
DEFAULTS_KEY = "components:defaults:{table}"
# показатель «насколько состав плат опирается на библиотеку»
COVERAGE_KEY = "boards:coverage"

_MISSING = object()


def timeout():
    """Сколько секунд держать значение. Ноль и меньше — не кэшировать."""
    return int(getattr(settings, "COMPONENTS_CACHE_SECONDS", DEFAULT_SECONDS))


def cached(key, producer, seconds=None):
    """Отдаёт значение из кэша, а если его там нет — считает и запоминает.

    ``None`` — законный ответ (например, «плат ещё нет»), поэтому промах
    отличается от сохранённого пустого значения по отдельному признаку, а
    не по ``is None``.
    """
    ttl = timeout() if seconds is None else seconds
    if ttl <= 0:
        return producer()

    try:
        value = cache.get(key, _MISSING)
    except Exception as exc:
        # кэш недоступен — считаем сами, страница от этого не страдает
        logger.warning("кэш недоступен при чтении %s: %s", key, exc)
        return producer()

    if value is not _MISSING:
        return value

    value = producer()
    try:
        cache.set(key, value, ttl)
    except Exception as exc:
        logger.warning("кэш недоступен при записи %s: %s", key, exc)
    return value


def drop(*keys):
    """Убирает значения из кэша — сразу после правки данных.

    Недоступный кэш здесь не страшнее, чем при чтении: значения и так
    живут ограниченное время, так что худшее последствие — счётчик,
    отставший на срок жизни записи.
    """
    if not keys:
        return
    try:
        cache.delete_many(list(keys))
    except Exception as exc:
        logger.warning("кэш недоступен при сбросе: %s", exc)


def drop_table(table):
    """Всё, что зависит от содержимого одной таблицы компонентов."""
    drop(FILTERS_KEY.format(table=table), DEFAULTS_KEY.format(table=table),
         COUNTS_KEY)


def drop_options():
    """Справочник списков поменялся: он влияет и на фильтры, и на формы."""
    from .registry import CATEGORIES

    keys = [OPTIONS_KEY.format(table=c.table) for c in CATEGORIES.values()]
    keys += [FILTERS_KEY.format(table=c.table) for c in CATEGORIES.values()]
    drop(*keys)
