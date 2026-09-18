"""Карточка ревизии: номера GCT и сведения о ходе работ.

Переименования (данные сохраняются, меняется только имя колонки):

* ``gct_pn`` -> ``gct_pcb``, «GCT P/N» -> «Соответствие PCB GCT»;
* ``old_oy_pn`` -> ``previous_revision``, «Старый OY P/N» -> «Предыдущая
  ревизия». Прежнее название вводило в заблуждение: в шапке BOM строка
  подписана «Old OY BOM P/N», но означает не устаревший номер этой же
  ревизии, а номер той, от которой она произошла.

Удаляется ``old_gct_pn`` («Старый GCT P/N») — **безвозвратно**. Сколько
непустых значений пропадёт, миграция печатает до удаления; перед запуском
снимите копию.

Добавляются восемь полей. Семь описывают ход работ по ревизии
(«Разработано», «Стадия разработки», «Поставщик PCB», «Шелкография»,
«ЭКБ», «Сборка», «Реестр МПТ»), восьмое — «Соответствие BOM GCT», парное к
``gct_pcb``: у печатной платы своё соответствие, у BOM своё, и совпадают
они не всегда.

Все восемь строковые. Значения приходят из карточек и таблиц, где пишут
свободно, и сузить тип до списка или даты вслепую значило бы потерять то,
что в них окажется на самом деле. Когда станет видно, что туда пишут,
сузить будет несложно — обратный переход дороже.
"""

from django.db import migrations, models

NEW_FIELDS = (
    ("gct_bom", 128, "Соответствие BOM GCT"),
    ("developed", 255, "Разработано"),
    ("stage", 255, "Стадия разработки"),
    ("pcb_supplier", 255, "Поставщик PCB"),
    ("silkscreen_status", 255, "Шелкография"),
    ("ekb", 255, "ЭКБ"),
    ("assembly", 255, "Сборка"),
    ("mpt_registry", 255, "Реестр МПТ"),
)


def count_before(apps, schema_editor):
    """Показывает, что потеряется вместе с «Старый GCT P/N»."""
    BoardRevision = apps.get_model("boards", "BoardRevision")
    found = BoardRevision.objects.exclude(old_gct_pn="").count()
    print(f"\n  Удаляется old_gct_pn; непустых значений: {found}\n")


def nothing(apps, schema_editor):
    """Обратный ход: колонка вернётся пустой, считать нечего."""


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0015_bom_header_to_card"),
    ]

    operations = [
        migrations.RenameField(model_name="boardrevision",
                               old_name="gct_pn", new_name="gct_pcb"),
        migrations.RenameField(model_name="boardrevision",
                               old_name="old_oy_pn",
                               new_name="previous_revision"),
        migrations.AlterField(
            model_name="boardrevision", name="gct_pcb",
            field=models.CharField(blank=True, default="", max_length=128,
                                   verbose_name="Соответствие PCB GCT"),
        ),
        migrations.AlterField(
            model_name="boardrevision", name="previous_revision",
            field=models.CharField(blank=True, default="", max_length=128,
                                   verbose_name="Предыдущая ревизия"),
        ),
        migrations.RunPython(count_before, nothing),
        migrations.RemoveField(model_name="boardrevision", name="old_gct_pn"),
    ] + [
        migrations.AddField(
            model_name="boardrevision", name=name,
            field=models.CharField(blank=True, default="", max_length=length,
                                   verbose_name=label),
        )
        for name, length, label in NEW_FIELDS
    ]
