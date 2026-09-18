"""Обход состава: вниз, вверх и сводка.

Все три задачи — один и тот же рекурсивный запрос по представлению
``bom_edge``, только в разные стороны. Представление сводит воедино два
хранилища состава: строки :class:`~servers.models.BomLine` и строки
текущей ревизии платы (см. миграцию 0002) — здесь про это знать уже не
нужно.

Почему рекурсивный запрос, а не обход в Python: глубина заранее неизвестна,
а на каждый уровень уходил бы отдельный запрос. PostgreSQL разворачивает
состав целиком за один заход.

Глубина ограничена :data:`MAX_DEPTH` не из экономии. Кольцо в составе
запрещено проверкой при сохранении, но проверка живёт в приложении, а
данные приходят и мимо него — импортом, руками через админку, чужим
скриптом. Без предела обход на кольце не закончится никогда.
"""

from django.db import connection

MAX_DEPTH = 12

# Разворот состава вниз. Количество перемножается по пути: две платы, в
# каждой по три конденсатора, дают шесть. Путь нужен и для показа отступом,
# и для защиты от повторного входа в ту же позицию
EXPLODE = """
WITH RECURSIVE tree AS (
    SELECT e.parent_id, e.child_id, e.oy_pn, e.gct_pn, e.description,
           e.quantity AS total, e.unit, e.designator, e.comment,
           1 AS depth, ARRAY[e.parent_id] AS path
    FROM bom_edge e
    WHERE e.parent_id = %s
  UNION ALL
    SELECT e.parent_id, e.child_id, e.oy_pn, e.gct_pn, e.description,
           t.total * e.quantity, e.unit, e.designator, e.comment,
           t.depth + 1, t.path || e.parent_id
    FROM bom_edge e
    JOIN tree t ON e.parent_id = t.child_id
    WHERE t.depth < %s AND NOT e.parent_id = ANY (t.path)
)
SELECT parent_id, child_id, oy_pn, gct_pn, description, total, unit,
       designator, comment, depth
FROM tree
ORDER BY depth, oy_pn
"""

# Обход вверх: та же рекурсия, стороны поменялись местами
WHERE_USED = """
WITH RECURSIVE up AS (
    SELECT e.parent_id, 1 AS depth, ARRAY[e.child_id] AS path
    FROM bom_edge e
    WHERE e.child_id = %s
  UNION ALL
    SELECT e.parent_id, u.depth + 1, u.path || e.child_id
    FROM bom_edge e
    JOIN up u ON e.child_id = u.parent_id
    WHERE u.depth < %s AND NOT e.parent_id = ANY (u.path)
)
SELECT DISTINCT parent_id, min(depth) AS depth FROM up GROUP BY parent_id
"""

# Достижимость: нужна только для запрета колец, поэтому останавливается
# на первом же попадании
REACHES = """
WITH RECURSIVE down AS (
    SELECT e.child_id, 1 AS depth FROM bom_edge e WHERE e.parent_id = %s
  UNION ALL
    SELECT e.child_id, d.depth + 1
    FROM bom_edge e JOIN down d ON e.parent_id = d.child_id
    WHERE d.depth < %s
)
SELECT 1 FROM down WHERE child_id = %s LIMIT 1
"""


def _rows(sql, params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def explode(item_id, depth=MAX_DEPTH):
    """Полный состав позиции: по строке на каждое вхождение, с отступами."""
    from .models import Item

    rows = _rows(EXPLODE, [item_id, depth])
    children = {item.id: item for item in Item.objects.filter(
        id__in={row[1] for row in rows if row[1]})}

    return [
        {"child": children.get(row[1]), "oy_pn": row[2], "gct_pn": row[3],
         "description": row[4], "quantity": row[5], "unit": row[6],
         "designator": row[7], "comment": row[8], "depth": row[9],
         # отступ уровня видимым знаком: подряд идущие пробелы в HTML
         # схлопываются, и вложенность на странице пропала бы
         "indent": "· " * (row[9] - 1)}
        for row in rows
    ]


def where_used(item_id, depth=MAX_DEPTH):
    """Позиции, в которые эта входит — прямо или через несколько уровней."""
    from .models import Item

    rows = _rows(WHERE_USED, [item_id, depth])
    levels = {row[0]: row[1] for row in rows}
    parents = Item.objects.filter(id__in=levels).order_by("kind", "oy_pn")
    return [{"item": parent, "depth": levels[parent.id]} for parent in parents]


def reaches(start_id, target_id, depth=MAX_DEPTH):
    """Лежит ли target внутри start на любой глубине."""
    if not start_id or not target_id:
        return False
    return bool(_rows(REACHES, [start_id, depth, target_id]))


def summary(item_id, depth=MAX_DEPTH):
    """Плоская сводка: каждая покупная позиция и сколько её всего.

    Складываются только листья — то, у чего своего состава нет. Узлы в
    сводку не идут: иначе плата попала бы в неё и сама, и своими
    компонентами, а итог получился бы вдвое.

    Ключ — номер: одна и та же деталь приходит и строкой состава, и из
    ревизии платы, и складывать её надо вместе. Единицы измерения в ключ
    входят тоже: 90 мм ленты и 3 штуки этикеток не суммируются.
    """
    totals = {}
    for row in explode(item_id, depth):
        child = row["child"]
        if child is not None and (child.lines.exists() or child.is_board):
            continue
        key = (row["oy_pn"] or row["gct_pn"] or row["description"], row["unit"])
        entry = totals.setdefault(key, {
            "oy_pn": row["oy_pn"], "gct_pn": row["gct_pn"],
            "description": row["description"], "unit": row["unit"],
            "quantity": 0, "child": child})
        entry["quantity"] += row["quantity"]
    return sorted(totals.values(), key=lambda entry: entry["oy_pn"] or "")
