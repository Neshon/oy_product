"""Плата перестаёт дублировать шапку BOM.

Номера, ревизии, дата, автор и файл принадлежат ревизии: у платы их было
столько же, сколько у последнего импорта, и при каждом новом BOM они
переписывались. Держать те же значения в двух местах — значит однажды их
развести, а карточка платы описывает модель, а не последний файл.

Изображения сторон убраны оттуда же: они относятся к конкретной ревизии —
у следующей ревизии плата выглядит иначе.

Остаются номер платы, наименование, тип, описание, применяемость,
характеристика, разработчик и указание на текущая ревизия.
"""

from django.db import migrations

REMOVED = [
    "oy_pn", "board_rev", "bom_rev", "gct_pn", "old_oy_pn", "old_gct_pn",
    "decimal_number", "bom_date", "author", "photo_top", "photo_bottom",
    "source_file",
]


class Migration(migrations.Migration):

    dependencies = [("boards", "0009_board_specs")]

    operations = [
        migrations.AlterModelOptions(
            name="board",
            options={"ordering": ("base_pn",), "verbose_name": "Плата",
                     "verbose_name_plural": "Платы"}),
    ] + [migrations.RemoveField("board", name) for name in REMOVED]
