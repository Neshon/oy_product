"""Краткая характеристика и изображения платы.

Страница платы в Confluence описывает её списком: «5 SFF»,
«PCIe Gen5 (32 Gb/s)», разъёмы, светодиоды. Набор пунктов у бэкплейна и у
платы управления разный, поэтому характеристика хранится текстом со строки
на пункт, а не колонками: колонок под все случаи не напасёшься.
"""

from django.db import migrations, models

FIELDS = [
    ("specs", models.TextField(blank=True, default="",
                               verbose_name="Краткая характеристика")),
    ("photo_top", models.CharField(blank=True, default="", max_length=500,
                                   verbose_name="Изображение — Top side")),
    ("photo_bottom", models.CharField(blank=True, default="", max_length=500,
                                      verbose_name="Изображение — Bottom side")),
]


class Migration(migrations.Migration):

    dependencies = [("boards", "0008_revision_links")]

    operations = [migrations.AddField("board", name, field)
                  for name, field in FIELDS]
