"""Представление ``bom_edge`` — единый вид на состав из двух хранилищ.

Состав лежит в двух местах: строки :class:`servers.BomLine` и строки
текущей ревизии платы. Разделение осмысленное — у плат есть ревизии,
импорт BOM и сравнение, ломать это ради единообразия не стали, — но обход
состава не должен об этом знать: иначе рекурсивный запрос пришлось бы
писать по двум таблицам, а каждый новый отчёт повторял бы это склеивание.

Строки замен (``kind = 'S'``) в состав не идут: это альтернативы, а не
отдельные вхождения, и в разузловании они удвоили бы количество.

Имя без схемы: представление создаётся в первой схеме пути поиска, там же,
где остальные таблицы Django (``POSTGRES_SCHEMA``). Колонка ``references``
у строки состава платы совпадает с ключевым словом SQL, поэтому в кавычках.
"""

from django.db import migrations

CREATE = """
CREATE OR REPLACE VIEW bom_edge AS
    SELECT l.parent_id,
           l.child_id,
           l.oy_pn,
           l.gct_pn,
           l.description,
           l.quantity,
           l.unit,
           l.designator,
           l.comment
    FROM servers_bomline l
    WHERE l.kind = 'M'
UNION ALL
    SELECT i.id AS parent_id,
           NULL::integer AS child_id,
           bi.oy_pn,
           bi.gbt_pn AS gct_pn,
           bi.description,
           COALESCE(bi.qty, 1)::numeric(12, 3) AS quantity,
           'шт'::varchar(8) AS unit,
           bi."references" AS designator,
           bi.comment
    FROM servers_item i
    JOIN boards_board b ON b.id = i.board_id
    JOIN boards_boardrevision r ON r.id = b.current_revision_id
    JOIN boards_boarditem bi ON bi.revision_id = r.id
    WHERE bi.kind = 'M';
"""

DROP = "DROP VIEW IF EXISTS bom_edge;"


class Migration(migrations.Migration):

    dependencies = [("servers", "0001_initial")]

    operations = [migrations.RunSQL(CREATE, DROP)]
