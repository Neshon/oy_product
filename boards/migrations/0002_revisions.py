"""Ревизии плат и связь строк состава с библиотекой компонентов.

Существующие составы не теряются: для каждой платы заводится ревизия №1,
и строки переносятся в неё.
"""

from django.db import migrations, models
import django.db.models.deletion


def make_first_revisions(apps, schema_editor):
    Board = apps.get_model("boards", "Board")
    BoardRevision = apps.get_model("boards", "BoardRevision")
    BoardItem = apps.get_model("boards", "BoardItem")

    for board in Board.objects.all():
        revision = BoardRevision.objects.create(
            board=board, number=1,
            gct_pn=board.gct_pn, old_oy_pn=board.old_oy_pn,
            old_gct_pn=board.old_gct_pn, decimal_number=board.decimal_number,
            bom_date=board.bom_date, author=board.author,
            source_file=board.source_file, imported_by=board.imported_by)
        BoardItem.objects.filter(board=board).update(revision=revision)
        board.current_revision = revision
        board.save(update_fields=["current_revision"])


def undo(apps, schema_editor):
    BoardItem = apps.get_model("boards", "BoardItem")
    for item in BoardItem.objects.select_related("revision"):
        item.board_id = item.revision.board_id
        item.save(update_fields=["board"])


class Migration(migrations.Migration):

    dependencies = [("boards", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="BoardRevision",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("number", models.PositiveIntegerField(verbose_name="Ревизия")),
                ("gct_pn", models.CharField(blank=True, default="", max_length=128,
                                            verbose_name="GCT P/N")),
                ("old_oy_pn", models.CharField(blank=True, default="", max_length=128,
                                               verbose_name="Старый OY P/N")),
                ("old_gct_pn", models.CharField(blank=True, default="", max_length=128,
                                                verbose_name="Старый GCT P/N")),
                ("decimal_number", models.CharField(blank=True, default="",
                                                    max_length=128,
                                                    verbose_name="Децимальный номер")),
                ("bom_date", models.CharField(blank=True, default="", max_length=64,
                                              verbose_name="Дата BOM")),
                ("author", models.CharField(blank=True, default="", max_length=255,
                                            verbose_name="Автор")),
                ("source_file", models.CharField(blank=True, default="", max_length=255,
                                                 verbose_name="Файл")),
                ("imported_at", models.DateTimeField(auto_now_add=True,
                                                     verbose_name="Импортировано")),
                ("imported_by", models.CharField(blank=True, default="", max_length=150,
                                                 verbose_name="Кто импортировал")),
                ("board", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="revisions", to="boards.board",
                    verbose_name="Плата")),
            ],
            options={
                "ordering": ("board", "-number"),
                "unique_together": {("board", "number")},
                "verbose_name": "Ревизия платы",
                "verbose_name_plural": "Ревизии плат",
            },
        ),
        migrations.AddField(
            model_name="board",
            name="current_revision",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to="boards.boardrevision",
                verbose_name="Текущая ревизия"),
        ),
        migrations.AddField(
            model_name="boarditem",
            name="revision",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="items", to="boards.boardrevision",
                verbose_name="Ревизия"),
        ),
        migrations.AddField(
            model_name="boarditem",
            name="component_table",
            field=models.CharField(blank=True, default="", max_length=64,
                                   verbose_name="Таблица компонента"),
        ),
        migrations.AddField(
            model_name="boarditem",
            name="component_id",
            field=models.IntegerField(blank=True, null=True,
                                      verbose_name="ID компонента"),
        ),
        migrations.AddField(
            model_name="boarditem",
            name="component_match",
            field=models.CharField(blank=True, default="", max_length=16,
                                   verbose_name="Как сопоставлено"),
        ),
        migrations.RunPython(make_first_revisions, undo),
        migrations.RemoveField(model_name="boarditem", name="board"),
        migrations.AlterField(
            model_name="boarditem",
            name="revision",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="items", to="boards.boardrevision",
                verbose_name="Ревизия"),
        ),
        migrations.AlterModelOptions(
            name="boarditem",
            options={
                "ordering": ("revision", "position", "kind", "id"),
                "verbose_name": "Строка состава",
                "verbose_name_plural": "Состав платы",
            },
        ),
        migrations.AddIndex(
            model_name="boarditem",
            index=models.Index(fields=["component_table", "component_id"],
                               name="boarditem_component_idx"),
        ),
    ]
