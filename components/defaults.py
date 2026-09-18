"""Что подставить в форму нового компонента.

Часть полей одинакова у всей группы: у каждой записи в ``RESISTOR`` в
столбце ``Group`` стоит одно и то же. Заполнять это руками при каждом
заведении — лишняя работа и лишний повод ошибиться: достаточно одной записи
с «Resistors» вместо «Resistor», и фильтр по группе разъедется надвое.

Значение берётся из самих данных — самое частое в этом столбце, — а не
выводится из имени таблицы. Как именно группа записана (``RESISTOR``,
``Resistor``, ``Резистор``), решает не Django: схему и содержимое ведёт не
он, и угадывать соглашение, которое можно просто прочитать, незачем.

Заглушки (``---``, ``?``) в расчёт не идут, иначе в новую запись подставилось
бы «не заполнено».
"""

from django.db.models import Count

from .cache import DEFAULTS_KEY, cached
from .db import fallback
from .matching import usable

# Поля, которые подставляются в новую запись. Только те, что действительно
# постоянны внутри группы: номинал или корпус у каждой записи свои, и
# подставлять «самый частый» было бы не помощью, а подсказкой неверного.
DEFAULT_FIELDS = ("group",)

# сколько самых частых значений просмотреть, прежде чем сдаться:
# на первых местах могут оказаться заглушки
CANDIDATES = 5


def defaults(category):
    """``{поле: значение}`` для формы нового компонента этой группы.

    Считается запросом на группировку по столбцу и кэшируется: ответ
    меняется примерно никогда, а заведение компонента — операция, к которой
    возвращаются по многу раз за день.
    """
    return cached(DEFAULTS_KEY.format(table=category.table),
                  lambda: _defaults(category))


def _defaults(category):
    found = {}
    for field in DEFAULT_FIELDS:
        value = _common_value(category, field)
        if value:
            found[field] = value
    return found


@fallback("", "значение по умолчанию для формы")
def _common_value(category, field):
    """Самое частое осмысленное значение столбца или пустая строка."""
    if field not in category.field_names:
        return ""
    rows = (category.model.objects
            # order_by() снимает Meta.ordering: иначе его поля попали бы
            # в GROUP BY и разрезали бы счётчик по каждой записи
            .order_by()
            .exclude(**{f"{field}__isnull": True})
            .exclude(**{field: ""})
            .values(field)
            .annotate(found=Count(field))
            .order_by("-found")[:CANDIDATES])
    for row in rows:
        value = usable(row[field])
        if value:
            return value
    return ""
