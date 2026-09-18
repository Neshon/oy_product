"""Снимает уникальность имени столбца.

Один и тот же столбец теперь можно завести несколько раз с разными
наборами таблиц: у Subgroup списки значений в разных группах разные.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("components", "0003_option_field")]

    operations = [
        migrations.AlterModelOptions(
            name="optionfield",
            options={
                "ordering": ("field", "id"),
                "verbose_name": "Столбец со списком",
                "verbose_name_plural": "Справочник столбцов",
            },
        ),
        migrations.AlterField(
            model_name="optionfield",
            name="field",
            field=models.CharField(
                max_length=64, verbose_name="Столбец",
                help_text="Имя поля модели, например smt_tht. Один столбец "
                          "можно завести несколько раз — с разными наборами таблиц"),
        ),
    ]
