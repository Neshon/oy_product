"""Шапка BOM переезжает в карточку ревизии.

Отдельной панели «шапка BOM» на странице состава больше нет: половина её
строк повторяла карточку, а половина описывала присланный файл, а не плату.

Что происходит с полями:

* ``decimal_number`` — то же самое, что «Децимальный номер узла печатного
  (PCBA)». Значения **переносятся** в ``decimal_pcba`` там, где оно пусто,
  и только потом колонка удаляется. Заполненную карточку не трогаем: её
  ведут люди, и она главнее присланного файла;
* ``gct_pn``, ``old_oy_pn``, ``old_gct_pn`` — остаются, просто показываются
  теперь в карточке ревизии, а не на странице состава;
* ``bom_date``, ``author`` — дата и автор, записанные **внутри файла**.
  Удаляются. Эти две строки на карточке теперь значат другое: когда и кто
  загрузил BOM в систему, а для этого уже есть ``imported_at`` и
  ``imported_by``;
* ``source_file`` — имя файла. Удаляется: одно и то же имя у десятка
  ревизий ничего не опознаёт.

``imported_at`` перестаёт быть ``auto_now_add``. Раньше он значил «когда
ревизия появилась» и при повторной загрузке BOM не менялся; теперь значит
«когда состав обновляли в последний раз» и проставляется при каждой
загрузке. У ревизий, заведённых руками, он пуст — состава из файла у них
не было.

Перед запуском снимите копию: удаление ``bom_date``, ``author`` и
``source_file`` необратимо. Сколько значений потеряется, миграция печатает
до удаления.
"""

from django.db import migrations, models

LOST = ("bom_date", "author", "source_file")


def decimal_to_card(apps, schema_editor):
    """Децимальный номер из шапки — в поле карточки, если оно пусто."""
    BoardRevision = apps.get_model("boards", "BoardRevision")

    moved = (BoardRevision.objects
             .exclude(decimal_number="")
             .filter(decimal_pcba="")
             .update(decimal_pcba=models.F("decimal_number")))

    kept = (BoardRevision.objects
            .exclude(decimal_number="")
            .exclude(decimal_pcba=models.F("decimal_number"))
            .count())

    print(f"\n  Децимальный номер перенесён в карточку: {moved}")
    if kept:
        print(f"  Карточка уже была заполнена и оставлена как есть: {kept} "
              f"(значения из шапки в этих ревизиях расходились с карточкой)")

    print("  Удаляются поля шапки; непустых значений:")
    for name in LOST:
        print(f"    {name}: {BoardRevision.objects.exclude(**{name: ''}).count()}")
    print()


def card_to_decimal(apps, schema_editor):
    """Обратный ход: вернуть децимальный номер в шапку.

    Копируем из карточки — другого источника уже нет. Это не полный откат:
    дата, автор и имя файла не восстановятся, они удалены.
    """
    BoardRevision = apps.get_model("boards", "BoardRevision")
    (BoardRevision.objects
     .exclude(decimal_pcba="")
     .update(decimal_number=models.F("decimal_pcba")))


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0014_drop_revision_extras"),
    ]

    operations = [
        migrations.RunPython(decimal_to_card, card_to_decimal),
        migrations.RemoveField(model_name="boardrevision", name="decimal_number"),
        migrations.RemoveField(model_name="boardrevision", name="bom_date"),
        migrations.RemoveField(model_name="boardrevision", name="author"),
        migrations.RemoveField(model_name="boardrevision", name="source_file"),
        migrations.AlterField(
            model_name="boardrevision",
            name="imported_at",
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name="Дата загрузки BOM"),
        ),
        migrations.AlterField(
            model_name="boardrevision",
            name="imported_by",
            field=models.CharField(blank=True, default="", max_length=150,
                                   verbose_name="Кто загрузил BOM"),
        ),
    ]
