"""Справочник столбцов: значения переезжают под столбец.

Раньше значение хранило имя поля прямо в себе; теперь есть отдельная
запись столбца со списком таблиц, а значения к ней привязаны.
Существующие данные переносятся автоматически.
"""

from django.db import migrations, models
import django.db.models.deletion


def move_values_to_fields(apps, schema_editor):
    OptionField = apps.get_model("components", "OptionField")
    OptionValue = apps.get_model("components", "OptionValue")

    for value in OptionValue.objects.all():
        option_field, _ = OptionField.objects.get_or_create(
            field=value.field, defaults={"tables": []})
        value.option_field = option_field
        value.save(update_fields=["option_field"])


def undo(apps, schema_editor):
    OptionValue = apps.get_model("components", "OptionValue")
    for value in OptionValue.objects.select_related("option_field"):
        value.field = value.option_field.field
        value.save(update_fields=["field"])


class Migration(migrations.Migration):

    dependencies = [("components", "0002_remove_optionvalue_order")]

    operations = [
        migrations.CreateModel(
            name="OptionField",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("field", models.CharField(
                    max_length=64, unique=True, verbose_name="Столбец",
                    help_text="Имя поля модели, например smt_tht")),
                ("label", models.CharField(
                    blank=True, default="", max_length=128,
                    verbose_name="Название",
                    help_text="Как столбец называть в интерфейсе. Пусто — как в базе")),
                ("tables", models.JSONField(
                    blank=True, default=list, verbose_name="Таблицы",
                    help_text="В каких таблицах работает список. Пусто — во всех")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
            ],
            options={
                "db_table": "oy_option_field",
                "ordering": ("field",),
                "verbose_name": "Столбец со списком",
                "verbose_name_plural": "Справочник столбцов",
            },
        ),
        # старое ограничение снимаем до удаления колонок
        migrations.AlterUniqueTogether(name="optionvalue", unique_together=set()),
        migrations.AddField(
            model_name="optionvalue",
            name="option_field",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="values", to="components.optionfield",
                verbose_name="Столбец"),
        ),
        migrations.RunPython(move_values_to_fields, undo),
        migrations.RemoveField(model_name="optionvalue", name="field"),
        migrations.RemoveField(model_name="optionvalue", name="group"),
        migrations.AlterField(
            model_name="optionvalue",
            name="option_field",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="values", to="components.optionfield",
                verbose_name="Столбец"),
        ),
        migrations.AlterModelOptions(
            name="optionvalue",
            options={
                "ordering": ("option_field", "value"),
                "verbose_name": "Значение",
                "verbose_name_plural": "Значения",
            },
        ),
        migrations.AlterUniqueTogether(
            name="optionvalue", unique_together={("option_field", "value")}),
    ]
