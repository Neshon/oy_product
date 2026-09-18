"""Создаёт таблицу справочника значений.

Остальные модели помечены managed = False, поэтому в миграциях их нет:
Django не создаёт и не изменяет таблицы компонентов.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="OptionValue",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("field", models.CharField(
                    max_length=64, verbose_name="Поле",
                    help_text="Имя поля модели, например smt_tht")),
                ("group", models.CharField(
                    blank=True, default="", max_length=64, verbose_name="Группа",
                    help_text="Пусто — значение доступно во всех группах компонентов")),
                ("value", models.CharField(max_length=255, verbose_name="Значение")),
                ("order", models.IntegerField(default=100, verbose_name="Порядок")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активно")),
            ],
            options={
                "db_table": "oy_option_value",
                "ordering": ("field", "order", "value"),
                "verbose_name": "Значение справочника",
                "verbose_name_plural": "Справочник значений",
                "unique_together": {("field", "group", "value")},
            },
        ),
    ]
