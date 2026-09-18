"""Выпадающие списки для полей компонентов.

Колонки в базе остаются текстовыми — их читает сторонний софт, и менять
тип на внешний ключ нельзя. Справочник задаёт только то, какие поля
показываются списком, в каких таблицах это работает и какие значения
доступны для выбора.

Настраивается в админке: раздел «Конструктор выпадающих списков».
"""

from .cache import OPTIONS_KEY, cached
from .db import fallback
from .models import OptionField
from .registry import CATEGORIES


def table_options(table):
    """Списки значений для таблицы: ``{имя поля: [значения]}``.

    Спрашивают об этом на каждую форму и на каждый набор фильтров, а меняется
    справочник только из админки, поэтому ответ кэшируется и сбрасывается при
    правке (см. ``components.apps``).
    """
    return cached(OPTIONS_KEY.format(table=table),
                  lambda: _table_options(table))


@fallback(dict, "справочник выпадающих списков")
def _table_options(table):
    """Тот же ответ, но всегда из базы.

    Если справочник пуст, таблица ещё не создана или база недоступна —
    возвращается пустой словарь, и поля остаются обычными текстовыми.
    """
    fields = (OptionField.objects
              .filter(is_active=True)
              .prefetch_related("values"))
    # общий список (таблицы не указаны) и список, заданный именно для
    # этой таблицы. Второй важнее: подгруппы у резисторов и разъёмов
    # разные, и общий набор для них смысла не имеет
    common, specific = {}, {}
    for option_field in fields:
        values = [v.value for v in option_field.values.all() if v.is_active]
        if not values:
            continue
        if not option_field.tables:
            common.setdefault(option_field.field, []).extend(values)
        elif table in option_field.tables:
            specific.setdefault(option_field.field, []).extend(values)

    merged = {**common, **specific}
    return {name: sorted(set(values)) for name, values in merged.items()}


def option_values(field, table):
    """Значения одного поля для конкретной таблицы."""
    return table_options(table).get(field, [])


def table_choices():
    """Список таблиц для выбора в админке."""
    return [(c.table, f"{c.table} — {c.title}") for c in CATEGORIES.values()]
