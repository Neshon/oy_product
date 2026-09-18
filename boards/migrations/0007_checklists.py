"""Разделы 2 и 3 шаблона: чек-листы и прикреплённые документы.

Ссылки на документы — поля ревизии: их четыре, они известны заранее и не
меняются. Строки чек-листов — отдельная таблица: их два с лишним десятка,
у каждой свой статус и комментарий, а сам список со временем пополняется.
"""

import django.db.models.deletion
from django.db import migrations, models

STATUSES = [
    ("", "не заполнено"),
    ("ok", "✅ есть"),
    ("review", "ревью"),
    ("no", "❌ нет"),
    ("na", "✕ не требуется"),
    ("attention", "❗ внимание"),
]

LINKS = [
    ("manufacture_url", "Папка Manufacture (диск R)"),
    ("assembly_url", "Папка Assembly (диск R)"),
    ("test_matrix_url", "Матрица тестового покрытия"),
    ("reference_bom_url", "Эталонный BOM-файл"),
]


def fill_checklists(apps, schema_editor):
    """Заводит строки чек-листов у ревизий, которые уже есть в базе."""
    from boards.checklists import TEMPLATE

    Revision = apps.get_model("boards", "BoardRevision")
    Item = apps.get_model("boards", "ChecklistItem")

    rows = []
    for revision in Revision.objects.all().iterator():
        for position, (group, title, responsibility, hint) in enumerate(
                TEMPLATE, start=1):
            rows.append(Item(revision=revision, group=group, position=position,
                             title=title, responsibility=responsibility,
                             hint=hint))
    Item.objects.bulk_create(rows, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [("boards", "0006_revision_card")]

    operations = [
        migrations.AddField(
            "boardrevision", name,
            models.CharField(blank=True, default="", max_length=500,
                             verbose_name=verbose))
        for name, verbose in LINKS
    ] + [
        migrations.CreateModel(
            name="ChecklistItem",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("group", models.CharField(db_index=True, max_length=16,
                                           verbose_name="Чек-лист")),
                ("position", models.IntegerField(default=0,
                                                 verbose_name="Порядок")),
                ("title", models.CharField(max_length=255,
                                           verbose_name="Документ")),
                ("responsibility", models.CharField(
                    blank=True, default="", max_length=255,
                    verbose_name="Зона ответственности")),
                ("hint", models.CharField(blank=True, default="", max_length=255,
                                          verbose_name="Примечание шаблона")),
                ("status", models.CharField(
                    blank=True, choices=STATUSES, default="", max_length=16,
                    verbose_name="Наличие документа")),
                ("comment", models.TextField(blank=True, default="",
                                             verbose_name="Комментарий")),
                ("url", models.CharField(blank=True, default="", max_length=500,
                                         verbose_name="Ссылка")),
                ("revision", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="checklist", to="boards.boardrevision",
                    verbose_name="Ревизия")),
            ],
            options={
                "ordering": ("revision", "group", "position", "id"),
                "unique_together": {("revision", "group", "title")},
                "verbose_name": "Строка чек-листа",
                "verbose_name_plural": "Чек-листы",
            },
        ),
        migrations.RunPython(fill_checklists, migrations.RunPython.noop),
    ]
