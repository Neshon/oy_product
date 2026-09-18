"""Ревизии из номера платы.

Номер вида HSBP-5S01-02C разбирается на плату (HSBP-5S01), ревизию платы
(0.2) и ревизию BOM (C). Из этого следует, что уже загруженные платы,
отличающиеся только суффиксом, — ревизии одной платы: миграция сводит их
вместе, перенося ревизии, и лишние записи удаляет.
"""

from django.db import migrations, models

from boards.revisions import parse_pn


def fill_and_merge(apps, schema_editor):
    Board = apps.get_model("boards", "Board")
    BoardRevision = apps.get_model("boards", "BoardRevision")

    # 1. разбираем номера
    for revision in BoardRevision.objects.select_related("board"):
        source = revision.board.oy_pn
        _, revision.board_rev, revision.bom_rev = parse_pn(source)
        revision.oy_pn = source
        revision.save(update_fields=["oy_pn", "board_rev", "bom_rev"])

    for board in Board.objects.all():
        board.base_pn, board.board_rev, board.bom_rev = parse_pn(board.oy_pn)
        board.save(update_fields=["base_pn", "board_rev", "bom_rev"])

    # 2. сводим платы с одинаковым базовым номером
    seen = {}
    for board in Board.objects.order_by("pk"):
        keeper = seen.get(board.base_pn)
        if keeper is None:
            seen[board.base_pn] = board
            continue

        # переносим ревизии, продолжая нумерацию хозяина
        last = (BoardRevision.objects.filter(board=keeper)
                .order_by("-number").first())
        next_number = (last.number + 1) if last else 1
        for revision in BoardRevision.objects.filter(board=board).order_by("number"):
            revision.board = keeper
            revision.number = next_number
            revision.save(update_fields=["board", "number"])
            next_number += 1

        # текущим оставляем ревизия с самой свежей ревизией
        newest = max(
            BoardRevision.objects.filter(board=keeper),
            key=lambda r: (r.board_rev or "", r.bom_rev or "", r.number))
        keeper.current_revision = newest
        keeper.oy_pn = newest.oy_pn or keeper.oy_pn
        _, keeper.board_rev, keeper.bom_rev = parse_pn(keeper.oy_pn)
        keeper.save(update_fields=["current_revision", "oy_pn",
                                   "board_rev", "bom_rev"])

        board.current_revision = None
        board.save(update_fields=["current_revision"])
        board.delete()


def undo(apps, schema_editor):
    """Разделить сведённые платы обратно нельзя — данные не терялись."""


class Migration(migrations.Migration):

    dependencies = [("boards", "0003_normalize_dates")]

    operations = [
        migrations.AddField(
            model_name="board",
            name="base_pn",
            field=models.CharField(max_length=128, null=True,
                                   verbose_name="Номер платы"),
        ),
        migrations.AddField(
            model_name="board",
            name="board_rev",
            field=models.CharField(blank=True, default="", max_length=16,
                                   verbose_name="Rev"),
        ),
        migrations.AddField(
            model_name="board",
            name="bom_rev",
            field=models.CharField(blank=True, default="", max_length=8,
                                   verbose_name="Rev BOM"),
        ),
        migrations.AddField(
            model_name="boardrevision",
            name="oy_pn",
            field=models.CharField(blank=True, default="", max_length=128,
                                   verbose_name="OY P/N"),
        ),
        migrations.AddField(
            model_name="boardrevision",
            name="board_rev",
            field=models.CharField(blank=True, default="", max_length=16,
                                   verbose_name="Rev"),
        ),
        migrations.AddField(
            model_name="boardrevision",
            name="bom_rev",
            field=models.CharField(blank=True, default="", max_length=8,
                                   verbose_name="Rev BOM"),
        ),
        migrations.RunPython(fill_and_merge, undo),
        # уникальность переезжает с полного номера на базовый
        migrations.AlterField(
            model_name="board",
            name="oy_pn",
            field=models.CharField(max_length=128, verbose_name="OY P/N"),
        ),
        migrations.AlterField(
            model_name="board",
            name="base_pn",
            field=models.CharField(max_length=128, null=True, unique=True,
                                   verbose_name="Номер платы"),
        ),
        migrations.AlterField(
            model_name="boardrevision",
            name="number",
            field=models.PositiveIntegerField(verbose_name="№"),
        ),
        migrations.AlterModelOptions(
            name="board",
            options={"ordering": ("base_pn", "oy_pn"),
                     "verbose_name": "Плата",
                     "verbose_name_plural": "Платы"},
        ),
    ]
