"""Убирает поле «Порядок»: значения показываются по алфавиту."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("components", "0001_optionvalue")]

    operations = [
        migrations.AlterModelOptions(
            name="optionvalue",
            options={
                "ordering": ("field", "value"),
                "verbose_name": "Значение справочника",
                "verbose_name_plural": "Справочник значений",
            },
        ),
        migrations.RemoveField(model_name="optionvalue", name="order"),
    ]
