"""Изображения платы: вид сверху и снизу.

Файлы лежат на диске (``MEDIA_ROOT``), в базе — только путь. ImageField, а
не строка с путём на диск R, как было раньше: путь вида
``R:\\2_PCB_DESIGN\\...`` в браузере не открывается и картинку в карточке не
покажет, а предпросмотр — это единственное, ради чего они здесь нужны.
"""

import boards.images
from django.db import migrations, models

FIELDS = [
    ("photo_top", models.ImageField(
        blank=True, upload_to=boards.images.upload_top,
        verbose_name="Изображение — Top side")),
    ("photo_bottom", models.ImageField(
        blank=True, upload_to=boards.images.upload_bottom,
        verbose_name="Изображение — Bottom side")),
]


class Migration(migrations.Migration):

    dependencies = [("boards", "0010_board_card_only")]

    operations = [migrations.AddField("board", name, field)
                  for name, field in FIELDS]
