"""Карточка ревизии приводится к шаблону страницы продукта «PCB».

Шаблон задаёт состав карточки, и модель следует ему построчно. Поля,
которых в шаблоне нет — стадия разработки, изготовитель PCB, сборка, ЭКБ,
реестр МПТ, — убираются: их никто не заполнял, а пустая колонка в карточке
хуже отсутствующей. Понадобятся — вернутся отдельной миграцией.

Добавляются недостающие: количество баллов по ПП РФ №719, маршрут
инструкций, фото сторон Top и Bottom и шапка карточки — утверждена она или
ещё в работе.
"""

from django.db import migrations, models

ADDED = [
    ("points", models.PositiveIntegerField(blank=True, null=True,
                                           verbose_name="Количество баллов")),
    ("instructions_url", models.CharField(blank=True, default="", max_length=500,
                                          verbose_name="Маршрут инструкций")),
    ("photo_top", models.CharField(blank=True, default="", max_length=500,
                                   verbose_name="Фото — сторона Top")),
    ("photo_bottom", models.CharField(blank=True, default="", max_length=500,
                                      verbose_name="Фото — сторона Bottom")),
    ("approved", models.BooleanField(default=False,
                                     verbose_name="Карточка утверждена")),
    ("approved_at", models.DateField(blank=True, null=True,
                                     verbose_name="Дата утверждения")),
]

REMOVED = ["stage", "pcb_supplier", "assembly", "components_origin",
           "mpt_registry"]


class Migration(migrations.Migration):

    dependencies = [("boards", "0005_board_cards")]

    operations = (
        [migrations.AddField("boardrevision", name, field) for name, field in ADDED]
        + [migrations.RemoveField("boardrevision", name) for name in REMOVED]
    )
