"""Новые названия в интерфейсе: конструктор выпадающих списков."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("components", "0004_optionfield_not_unique")]

    operations = [
        migrations.AlterModelOptions(
            name="optionfield",
            options={
                "ordering": ("field", "id"),
                "verbose_name": "Выпадающий список",
                "verbose_name_plural": "Столбцы со списками",
            },
        ),
    ]
