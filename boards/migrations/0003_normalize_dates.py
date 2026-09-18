"""Приводит уже загруженные даты BOM к виду ДД.ММ.ГГГГ.

Импорт нормализует дату сам, но платы, загруженные раньше, хранят её так,
как было в файле: встречались и «12.11.2025», и «2025.09.30».
"""

from django.db import migrations

from boards.importer import normalize_date


def normalize(apps, schema_editor):
    for model_name in ("Board", "BoardRevision"):
        model = apps.get_model("boards", model_name)
        changed = []
        for row in model.objects.exclude(bom_date=""):
            fixed = normalize_date(row.bom_date)
            if fixed != row.bom_date:
                row.bom_date = fixed
                changed.append(row)
        model.objects.bulk_update(changed, ["bom_date"], batch_size=500)


def undo(apps, schema_editor):
    """Обратного преобразования нет: исходный формат не сохранялся."""


class Migration(migrations.Migration):

    dependencies = [("boards", "0002_revisions")]

    operations = [migrations.RunPython(normalize, undo)]
