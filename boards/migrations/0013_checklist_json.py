"""Чек-листы ревизии — одним полем JSON вместо таблицы строк.

Что происходит:

1. у ревизии появляется поле ``checklist``;
2. ответы из ``ChecklistItem`` переезжают в него;
3. таблица строк удаляется.

**Миграция обратима.** Обратный ход раскладывает JSON обратно в строки —
описание берётся из шаблона, а у строк вне шаблона оно лежит в самой
записи. Это не украшение: ошибиться тут значит потерять работу людей за
несколько месяцев, и возможность вернуться назад одной командой дороже
десятка строк кода. Перед запуском всё равно снимите копию.

Что не переезжает: название, зона ответственности, формат и примечание для
строк **из шаблона**. Они одинаковы у всех ревизий и теперь живут в
``boards/checklists.py``. Для строк, которых в шаблоне нет, описание
переезжает вместе с ответом — взять его больше неоткуда.

Отдельно про формат файла. У шаблонных строк он в базе был, а в шаблоне
пока пуст — вписать его туда я не могу, не зная ваших данных. Поэтому при
переносе миграция печатает, какие форматы встретились у шаблонных строк,
готовым куском для TEMPLATE: перенесите их в ``boards/checklists.py``, и
формат появится сразу у всех ревизий. Значения из базы при этом теряются —
это единственная потеря во всём переносе, и она намеренная: хранить у
каждой ревизии свою копию одного и того же «*.brd» незачем.
"""

from django.db import migrations, models

# (группа, название) строк шаблона — дословно как в boards/checklists.py на
# момент миграции. Копия намеренная: миграции нельзя привязывать к живому
# коду, иначе правка шаблона задним числом меняет смысл уже применённой
# миграции.
TEMPLATE_KEYS = {
    ("pcb", "Бланк заказа"),
    ("pcb", "Gerber"),
    ("pcb", "Stackup"),
    ("pcb", "Изображение платы"),
    ("smt", "ODB++"),
    ("smt", "Лист изменений дизайна PCB"),
    ("smt", "Инструкция по сборке печатного узла"),
    ("smt", "Pick-and-place"),
    ("smt", "Сборочный чертёж узла (iBOM)"),
    ("smt", "Схема Э3 PDF"),
    ("smt", "BOM"),
    ("smt", "Лист изменений BOM"),
    ("smt", "Gerber (for Stencil)"),
    ("smt", "Инструкция для выводного монтажа"),
    ("smt", "3D-модель печатного узла"),
    ("smt", "Список микросхем, подлежащих программированию"),
    ("smt", "Инструкции по прошивке микросхем"),
    ("smt", "Файлы для прошивки микросхем"),
    ("smt", "Инструкции по первичной диагностике печатной платы"),
    ("smt", "Инструкция по тестированию плат"),
    ("smt", "Базовый SKU-файл"),
    ("smt2", "Структурная схема"),
    ("smt2", "Список I2C устройств"),
    ("smt2", "Power sequence печатной платы"),
    ("smt2", "Инструкция по среде тестирования"),
    ("smt2", "Фото"),
}

ANSWER_FIELDS = ("status", "comment", "url")
DESCRIPTION_FIELDS = ("responsibility", "hint", "file_format")


def to_json(apps, schema_editor):
    """Строки -> одно поле у ревизии."""
    ChecklistItem = apps.get_model("boards", "ChecklistItem")
    BoardRevision = apps.get_model("boards", "BoardRevision")

    collected = {}
    for item in ChecklistItem.objects.all().iterator(chunk_size=2000):
        entry = {name: getattr(item, name) or ""
                 for name in ANSWER_FIELDS}
        if (item.group, item.title) not in TEMPLATE_KEYS:
            # строки нет в шаблоне: описание ей взять больше неоткуда
            entry.update({name: getattr(item, name) or ""
                          for name in DESCRIPTION_FIELDS})
        entry = {name: value for name, value in entry.items() if value}
        if not entry:
            continue        # незаполненная строка шаблона — хранить нечего
        (collected.setdefault(item.revision_id, {})
                  .setdefault(item.group, {})[item.title]) = entry

    for revision_id, stored in collected.items():
        BoardRevision.objects.filter(pk=revision_id).update(checklist=stored)

    _report_formats(ChecklistItem)


def _report_formats(ChecklistItem):
    """Печатает форматы шаблонных строк — их место теперь в TEMPLATE.

    Печатаем прямо в миграции, а не отдельной командой: команду забудут
    запустить до переноса, а после него данных уже не будет.
    """
    seen = {}
    rows = (ChecklistItem.objects
            .exclude(file_format="")
            .values_list("group", "title", "file_format"))
    for group, title, file_format in rows:
        if (group, title) in TEMPLATE_KEYS:
            seen.setdefault((group, title), set()).add(file_format)

    if not seen:
        return

    print("\n  Форматы файлов у строк шаблона перенесите в TEMPLATE "
          "(boards/checklists.py):")
    for (group, title), formats in sorted(seen.items()):
        chosen = sorted(formats)
        note = "" if len(chosen) == 1 else f"   # встречались и другие: {chosen[1:]}"
        print(f"    {group!r}, {title!r} -> {chosen[0]!r}{note}")
    print()


def to_rows(apps, schema_editor):
    """Одно поле -> обратно в строки. Нужен только для отката."""
    ChecklistItem = apps.get_model("boards", "ChecklistItem")
    BoardRevision = apps.get_model("boards", "BoardRevision")

    # порядок и описание шаблонных строк восстанавливаем по тому же списку
    order = {key: index for index, key in enumerate(sorted(TEMPLATE_KEYS), 1)}

    rows = []
    for revision in BoardRevision.objects.all().iterator(chunk_size=500):
        stored = revision.checklist if isinstance(revision.checklist, dict) else {}
        for group, titles in stored.items():
            if not isinstance(titles, dict):
                continue
            for title, entry in titles.items():
                if not isinstance(entry, dict):
                    continue
                rows.append(ChecklistItem(
                    revision_id=revision.pk, group=group, title=title,
                    position=order.get((group, title), 100),
                    status=entry.get("status", ""),
                    comment=entry.get("comment", ""),
                    url=entry.get("url", ""),
                    responsibility=entry.get("responsibility", ""),
                    hint=entry.get("hint", ""),
                    file_format=entry.get("file_format", "")))
    ChecklistItem.objects.bulk_create(rows, batch_size=1000)


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0012_revision_photos"),
    ]

    operations = [
        migrations.AddField(
            model_name="boardrevision",
            name="checklist",
            field=models.JSONField(blank=True, default=dict,
                                   verbose_name="Ответы чек-листов"),
        ),
        migrations.RunPython(to_json, to_rows),
        migrations.DeleteModel(name="ChecklistItem"),
    ]
