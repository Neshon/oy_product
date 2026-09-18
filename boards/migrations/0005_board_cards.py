"""Карточки платы и ревизии.

У платы появляется то, что не меняется от ревизии к ревизии (назначение,
тип, разработчик), у ревизии — то, что своё у каждого: исполнение, номера
PCB и PCBA, шелкография, стадия, изготовитель.

Поля отдельными колонками, а не общим списком: по типу платы и стадии
фильтруют реестр, а по децимальному номеру ищут — в свободном списке ни
того, ни другого не сделать.
"""

from django.db import migrations, models

BOARD_TYPES = [
    ("motherboard", "Материнская плата"),
    ("backplane", "Бэкплейн"),
    ("riser", "Райзер"),
    ("interposer", "Интерпозер"),
    ("adapter", "Адаптер"),
    ("control", "Плата управления"),
    ("indicator", "Плата индикации"),
    ("power", "Плата питания"),
    ("other", "Прочее"),
]

STAGES = [
    ("EVT", "EVT — опытный образец"),
    ("DVT", "DVT — конструкторская проверка"),
    ("PVT", "PVT — проверка производства"),
    ("MP", "MP — серийное производство"),
]

BOARD_FIELDS = [
    ("name", models.CharField(blank=True, default="", max_length=255,
                              verbose_name="Наименование")),
    ("board_type", models.CharField(blank=True, choices=BOARD_TYPES,
                                    db_index=True, default="", max_length=16,
                                    verbose_name="Тип платы")),
    ("purpose", models.TextField(blank=True, default="",
                                 verbose_name="Назначение")),
    ("applicability", models.TextField(blank=True, default="",
                                       verbose_name="Применяемость")),
    ("developer", models.CharField(blank=True, default="", max_length=255,
                                   verbose_name="Компания-разработчик")),
]

REVISION_FIELDS = [
    ("variant", models.CharField(blank=True, db_index=True, default="",
                                 max_length=4, verbose_name="Исполнение")),
    ("pcb_name", models.CharField(blank=True, default="", max_length=128,
                                  verbose_name="Наименование PCB")),
    ("bom_name", models.CharField(blank=True, default="", max_length=128,
                                  verbose_name="Наименование BOM")),
    ("silkscreen", models.CharField(blank=True, default="", max_length=128,
                                    verbose_name="Обозначение на шелкографии")),
    ("panel_count", models.PositiveIntegerField(
        blank=True, null=True, verbose_name="Плат в мультизаготовке")),
    ("decimal_pcba", models.CharField(blank=True, default="", max_length=128,
                                      verbose_name="Децимальный номер PCBA")),
    ("decimal_pcb", models.CharField(blank=True, default="", max_length=128,
                                     verbose_name="Децимальный номер PCB")),
    ("pcb_type", models.CharField(blank=True, default="", max_length=128,
                                  verbose_name="Вид платы (ПП РФ №719)")),
    ("stage", models.CharField(blank=True, choices=STAGES, db_index=True,
                               default="", max_length=8,
                               verbose_name="Стадия разработки")),
    ("pcb_supplier", models.CharField(blank=True, default="", max_length=255,
                                      verbose_name="Изготовитель PCB")),
    ("assembly", models.CharField(blank=True, default="", max_length=255,
                                  verbose_name="Сборка")),
    ("components_origin", models.CharField(blank=True, default="",
                                           max_length=255, verbose_name="ЭКБ")),
    ("mpt_registry", models.CharField(blank=True, default="", max_length=255,
                                      verbose_name="Реестр МПТ")),
    ("fru_megarac", models.CharField(blank=True, default="", max_length=255,
                                     verbose_name="FRU-шаблон (MegaRAC)")),
    ("fru_oybmc", models.CharField(blank=True, default="", max_length=255,
                                   verbose_name="FRU-шаблон (OYBMC)")),
    ("spec_1c", models.CharField(blank=True, default="", max_length=255,
                                 verbose_name="Ресурсная спецификация (1С)")),
    ("spec_1c_url", models.CharField(blank=True, default="", max_length=500,
                                     verbose_name="Ссылка на спецификацию (1С)")),
    ("note", models.TextField(blank=True, default="",
                              verbose_name="Примечание")),
]


def fill_variants(apps, schema_editor):
    """Проставляет исполнение ревизиям, заведённым до этой миграции.

    Разбор берём живой: правило одно и то же, а дублировать его в миграции
    значит развести две копии, которые однажды разойдутся.
    """
    from boards.revisions import variant_of

    Revision = apps.get_model("boards", "BoardRevision")
    for revision in Revision.objects.exclude(oy_pn="").iterator():
        variant = variant_of(revision.oy_pn)
        if variant:
            revision.variant = variant
            revision.save(update_fields=["variant"])


class Migration(migrations.Migration):

    dependencies = [("boards", "0004_pn_revisions")]

    operations = (
        [migrations.AddField("board", name, field) for name, field in BOARD_FIELDS]
        + [migrations.AddField("boardrevision", name, field)
           for name, field in REVISION_FIELDS]
        + [migrations.RunPython(fill_variants, migrations.RunPython.noop)]
    )
