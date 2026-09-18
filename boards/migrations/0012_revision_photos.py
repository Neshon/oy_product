"""Изображения ревизии: вид сверху и снизу, как у платы.

До этого в карточке ревизии было два текстовых поля со ссылками — их
заполняли руками или они приезжали из карточек Confluence. Ссылка ведёт
кто куда: в Confluence, на диск R, иногда в никуда. Показать по ней
картинку нельзя, а предпросмотр — единственное, ради чего снимки здесь
нужны.

Поэтому не замена, а разделение:

* прежние текстовые поля переименованы в ``photo_*_url`` — данные
  остаются на месте, старые ссылки продолжают открываться;
* под именами ``photo_top`` / ``photo_bottom`` заведены ImageField —
  туда грузят файл, и он виден в карточке.

Переливать одно в другое нечем: по ссылке лежит что угодно, и выкачать
файл оттуда мы не можем. Оба поля живут рядом, пока ссылки не вытеснятся
загруженными снимками сами.

Порядок операций важен: сперва переименование, иначе AddField упёрся бы в
занятое имя.
"""

import boards.images
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0011_board_photos"),
    ]

    operations = [
        migrations.RenameField(
            model_name="boardrevision",
            old_name="photo_top",
            new_name="photo_top_url",
        ),
        migrations.RenameField(
            model_name="boardrevision",
            old_name="photo_bottom",
            new_name="photo_bottom_url",
        ),
        migrations.AlterField(
            model_name="boardrevision",
            name="photo_top_url",
            field=models.CharField(blank=True, default="", max_length=500,
                                   verbose_name="Фото — сторона Top (ссылка)"),
        ),
        migrations.AlterField(
            model_name="boardrevision",
            name="photo_bottom_url",
            field=models.CharField(blank=True, default="", max_length=500,
                                   verbose_name="Фото — сторона Bottom (ссылка)"),
        ),
        migrations.AddField(
            model_name="boardrevision",
            name="photo_top",
            field=models.ImageField(blank=True,
                                    upload_to=boards.images.revision_top,
                                    verbose_name="Изображение — Top side"),
        ),
        migrations.AddField(
            model_name="boardrevision",
            name="photo_bottom",
            field=models.ImageField(blank=True,
                                    upload_to=boards.images.revision_bottom,
                                    verbose_name="Изображение — Bottom side"),
        ),
    ]
