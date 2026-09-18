"""Из карточки ревизии убраны четыре поля.

* ``photo_top_url``, ``photo_bottom_url`` — ссылки на фото из карточек
  Confluence. Вели кто куда и картинку показать не могли; с появлением
  загрузки снимков (0012) стали лишней парой строк под самими снимками.
* ``instructions_url`` — маршрут инструкций.
* ``note`` — примечание.

**Данные удаляются безвозвратно.** RemoveField обратим только по схеме:
откат вернёт колонки, но пустыми. Поэтому перед запуском — копия:

    pg_dump -Fc -d oy_system_db -f before_drop_revision_extras.dump

Чтобы не удалять вслепую, миграция сначала печатает, сколько ревизий имели
непустое значение в каждом поле. Если число окажется больше ожидаемого —
остановитесь и откатитесь на копию: это дешевле, чем выяснять потом, что
именно пропало.
"""

from django.db import migrations

FIELDS = ("photo_top_url", "photo_bottom_url", "instructions_url", "note")


def count_before(apps, schema_editor):
    """Печатает, сколько значений сейчас потеряется."""
    BoardRevision = apps.get_model("boards", "BoardRevision")

    print("\n  Удаляются поля карточки ревизии; непустых значений:")
    for name in FIELDS:
        found = BoardRevision.objects.exclude(**{name: ""}).count()
        print(f"    {name}: {found}")
    print()


def nothing(apps, schema_editor):
    """Обратный ход: считать уже нечего, колонки пусты."""


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0013_checklist_json"),
    ]

    operations = [
        migrations.RunPython(count_before, nothing),
        migrations.RemoveField(model_name="boardrevision", name="photo_top_url"),
        migrations.RemoveField(model_name="boardrevision", name="photo_bottom_url"),
        migrations.RemoveField(model_name="boardrevision", name="instructions_url"),
        migrations.RemoveField(model_name="boardrevision", name="note"),
    ]
