"""Подсказка следующего OY ID.

В данных идентификатор выглядит как ``ID_R_000221``: буква обозначает группу
компонентов, дальше шестизначный номер. Номер подбирается по уже занятым:
берётся максимальный для этой буквы и увеличивается на единицу.

Просматриваются рабочая таблица и её таблица замен — у аналогов OY ID тот
же, что у оригинала, и номер из них тоже занят.

Считает это база, а не Python: разбор ``ID_X_NNNNNN`` укладывается в
группировку по букве с ``COUNT`` и ``MAX``, то есть в один запрос на
таблицу. Раньше форма создания компонента вычитывала из таблицы все
идентификаторы целиком — десятки тысяч строк по сети ради двух чисел.

Если база выражение не приняла, остаётся прежний путь: те же значения
потоком и разбор регулярным выражением на нашей стороне. Ответ от этого
не меняется, меняется только цена.
"""

import re

from django.db.models import BigIntegerField, Count, Max
from django.db.models.functions import Cast, Substr, Upper

from .db import fallback

PATTERN = re.compile(r"^ID_([A-Za-z])_(\d+)$")
DIGITS = 6
CHUNK = 2000

# то же правило, что и в PATTERN, но для PostgreSQL: только по таким
# строкам номер вообще можно приводить к числу
SQL_PATTERN = r"^ID_[A-Za-z]_[0-9]+$"

# «ID_» — три символа, буква четвёртая, подчёркивание пятое,
# значит цифры начинаются с шестого символа и идут до конца строки
LETTER_POSITION = 4
NUMBER_POSITION = 6


@fallback(None, "нумерация OY ID одним запросом")
def _count_by_query(category):
    """``{буква: (сколько, максимум)}`` одним запросом.

    ``None`` — база выражение не приняла или недоступна; решать, что с этим
    делать, будет вызывающий.
    """
    rows = (category.model.objects
            .filter(oy_id__regex=SQL_PATTERN)
            # order_by() снимает Meta.ordering: иначе его поля попали бы
            # в GROUP BY и счётчик разрезало бы по каждой записи
            .order_by()
            .annotate(
                letter=Upper(Substr("oy_id", LETTER_POSITION, 1)),
                number=Cast(Substr("oy_id", NUMBER_POSITION),
                            BigIntegerField()))
            .values("letter")
            .annotate(found=Count("letter"), top=Max("number")))
    return {row["letter"]: (row["found"], row["top"] or 0) for row in rows}


@fallback(None, "нумерация OY ID обходом таблицы")
def _count_by_scan(category):
    """Запасной путь: значения потоком, разбор на нашей стороне.

    В больших таблицах идентификаторов десятки тысяч, поэтому весь список в
    памяти не держим — на каждую букву нужны только два числа.
    """
    seen = {}
    values = (category.model.objects
              .filter(oy_id__startswith="ID_")
              .order_by()
              .values_list("oy_id", flat=True)
              .iterator(chunk_size=CHUNK))
    for value in values:
        match = PATTERN.match((value or "").strip())
        if not match:
            continue
        letter = match.group(1).upper()
        count, top = seen.get(letter, (0, 0))
        seen[letter] = (count + 1, max(top, int(match.group(2))))
    return seen


def _collect(category, seen):
    """Добавляет в ``seen`` данные одной таблицы. False — таблицу не прочесть."""
    if "oy_id" not in category.field_names:
        return True

    counted = _count_by_query(category)
    if counted is None:
        counted = _count_by_scan(category)
    if counted is None:
        return False

    for letter, (count, top) in counted.items():
        was_count, was_top = seen.get(letter, (0, 0))
        seen[letter] = (was_count + count, max(was_top, top))
    return True


def next_oy_id(category):
    """Следующий свободный OY ID для группы или пустая строка."""
    from .registry import counterpart

    seen = {}
    for item in (category, counterpart(category)):
        if item is None:
            continue
        if not _collect(item, seen):
            return ""

    if not seen:
        return ""

    # буква группы — та, что встречается чаще всего в этих таблицах
    letter = max(seen, key=lambda key: seen[key][0])
    return f"ID_{letter}_{seen[letter][1] + 1:0{DIGITS}d}"
