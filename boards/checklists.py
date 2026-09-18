"""Чек-листы ревизии: какие документы должны быть готовы.

Состав строк задан шаблоном страницы продукта «PCB» и одинаков для всех
ревизий, поэтому он лежит здесь списком, а не в базе. Иначе у одной ревизии
окажется 22 строки, у другой 19, и сравнить готовность двух ревизий будет
нельзя.

**Что где хранится.** В шаблоне — всё, что описывает сам документ: название,
зона ответственности, формат файла, примечание. Это справочные сведения,
одинаковые у всех ревизий; раньше они лежали отдельной записью на каждую
строку каждой ревизии — два десятка копий формулировки «R&D (Отдел печатных
узлов и элементной базы)» на одну ревизию. В базе — только ответы:
готовность, комментарий, ссылка. Вот они и правда свои у каждой ревизии.

Ответы лежат одним полем ``BoardRevision.checklist`` (JSON) вида::

    {"pcb": {"Бланк заказа": {"status": "ok", "comment": "", "url": ""}}}

Раньше это были записи ``ChecklistItem`` — по два с лишним десятка на
ревизию. Отдельными записями они были нужны, пока в них хранилось описание
документа; когда осталась одна готовность, запись перестала себя окупать:
показ карточки стоил отдельного запроса, заведение ревизии — двадцати двух
вставок, а состав приходилось поддерживать командой «досоздать недостающие
строки», потому что шаблон со временем пополняется. Теперь он пополняется
сам собой: строка есть, потому что она есть в шаблоне.

Строки, которых в шаблоне нет, тоже бывают: на странице Confluence документ
есть, а в шаблон его не завели. Такие несут описание рядом с ответом — им
взять его больше неоткуда.
"""

from dataclasses import dataclass, field

# Кто отвечает за документ. Вынесено в константы: одна и та же длинная
# формулировка повторяется в десятке строк, и опечатка в ней рассыпала бы
# группировку по отделам
PCB_DEPT = "R&D (Отдел печатных узлов и элементной базы)"
HW_DEPT = "R&D (Отдел аппаратной архитектуры и схемотехники)"
DOC_DEPT = "R&D (Отдел технической документации)"
SW_DEPT = "R&D (Отдел программного обеспечения)"

PCB = "pcb"
SMT = "smt"
SMT_SECOND = "smt2"

# Групп в шаблоне три, но на страницах встречаются ещё две — исходные
# файлы и РКД для сертификации. Они не в шаблоне, поэтому своих строк не
# получают, но если пришли со страницы, показать их надо
SOURCE = "source"
RKD = "rkd"
OTHER = "other"

# (код, полное название, короткое). Полное стоит в заголовке панели, где
# место есть; короткое — на вкладке, где его нет: пять названий по сорок
# знаков переносят полоску вкладок на три строки, и выбирать из них
# приходится чтением, а не взглядом.
GROUPS = (
    (SOURCE, "Чек-лист исходных файлов PCB", "Исходные файлы"),
    (PCB, "Чек-лист для производства печатной платы (PCB)", "Производство PCB"),
    (SMT, "Чек-лист для SMT-цеха", "SMT-цех"),
    (SMT_SECOND, "Чек-лист для SMT-цеха · второй приоритет", "SMT · второй"),
    (RKD, "Список РКД на ПП для сертификации", "РКД"),
    (OTHER, "Прочие документы", "Прочее"),
)

# Ответ в колонке «Наличие документа». Раньше жил в модели ChecklistItem;
# модели больше нет, а варианты никуда не делись
EMPTY = ""
OK = "ok"
NONE = "no"
NOT_NEEDED = "na"
REVIEW = "review"
ATTENTION = "attention"

STATUSES = (
    (EMPTY, "не заполнено"),
    (OK, "✅ есть"),
    (REVIEW, "ревью"),
    (NONE, "❌ нет"),
    (NOT_NEEDED, "✕ не требуется"),
    (ATTENTION, "❗ внимание"),
)
STATUS_LABELS = dict(STATUSES)

# (группа, название документа, зона ответственности, примечание, формат)
#
# Формат файла стоит здесь, а не в базе: у одного документа он одинаков во
# всех ревизиях. Пустой — значит в шаблоне продукта формат не указан;
# впишите, и он появится сразу у всех ревизий, старых тоже.
TEMPLATE = (
    (PCB, "Бланк заказа", PCB_DEPT, "", ""),
    (PCB, "Gerber", PCB_DEPT, "", ""),
    (PCB, "Stackup", PCB_DEPT, "", ""),
    (PCB, "Изображение платы", PCB_DEPT, "", ""),

    (SMT, "ODB++", PCB_DEPT, "", ""),
    (SMT, "Лист изменений дизайна PCB", PCB_DEPT, "При изменении версии PCB", ""),
    (SMT, "Инструкция по сборке печатного узла", DOC_DEPT, "ИС1", ""),
    (SMT, "Pick-and-place", PCB_DEPT, "", ""),
    (SMT, "Сборочный чертёж узла (iBOM)", PCB_DEPT, "", ""),
    (SMT, "Схема Э3 PDF", HW_DEPT, "", ""),
    (SMT, "BOM", HW_DEPT, "", ""),
    (SMT, "Лист изменений BOM", HW_DEPT, "При изменении версии BOM", ""),
    (SMT, "Gerber (for Stencil)", PCB_DEPT, "", ""),
    (SMT, "Инструкция для выводного монтажа", DOC_DEPT, "ИВ1", ""),
    (SMT, "3D-модель печатного узла", PCB_DEPT, "", ""),
    (SMT, "Список микросхем, подлежащих программированию", HW_DEPT, "", ""),
    (SMT, "Инструкции по прошивке микросхем", DOC_DEPT, "ИП1", ""),
    (SMT, "Файлы для прошивки микросхем", SW_DEPT, "", ""),
    (SMT, "Инструкции по первичной диагностике печатной платы", DOC_DEPT, "ИД1", ""),
    (SMT, "Инструкция по тестированию плат", HW_DEPT,
     "В том числе чтение логов · ИТ1", ""),
    (SMT, "Базовый SKU-файл", SW_DEPT, "FRU-шаблон печатного узла", ""),

    (SMT_SECOND, "Структурная схема", HW_DEPT,
     "Э2, I2C Diagram, Power Diagram", ""),
    (SMT_SECOND, "Список I2C устройств", HW_DEPT,
     "Таблица устройств с описанием и адресами", ""),
    (SMT_SECOND, "Power sequence печатной платы", HW_DEPT, "", ""),
    (SMT_SECOND, "Инструкция по среде тестирования", DOC_DEPT, "", ""),
    (SMT_SECOND, "Фото", PCB_DEPT, "Сторона Top и Bottom", ""),
)

TEMPLATE_KEYS = frozenset((row[0], row[1]) for row in TEMPLATE)

# Ключи, под которыми в JSON лежит ответ. Всё остальное в записи —
# описание документа, и бывает оно только у строк вне шаблона
ANSWER_KEYS = ("status", "comment", "url")
DESCRIPTION_KEYS = ("responsibility", "hint", "file_format")


@dataclass
class Row:
    """Строка чек-листа для показа и правки.

    Собирается на лету из шаблона и сохранённых ответов; в базе как целое не
    лежит. Обычный объект, не модель: ни сохранять её, ни искать не нужно —
    за это отвечает ревизия целиком.
    """

    group: str
    title: str
    responsibility: str = ""
    hint: str = ""
    file_format: str = ""
    status: str = ""
    comment: str = ""
    url: str = ""
    # строки нет в шаблоне: пришла со страницы Confluence и описание несёт
    # с собой, потому что взять его больше неоткуда
    extra: bool = False

    @property
    def is_filled(self):
        return bool(self.status)

    @property
    def status_display(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def details(self):
        """Справка о документе одной строкой — под его названием.

        Формат, зона ответственности и примечание занимали по колонке
        каждая. Колонки были широкие и почти всегда с одинаковым
        содержимым: таблица растягивалась, а читали в ней два поля —
        название и готовность.
        """
        return " · ".join(part for part in
                          (self.file_format, self.responsibility, self.hint)
                          if part)


@dataclass
class Group:
    """Один чек-лист: заголовок и его строки."""

    group: str
    title: str
    short: str = ""
    rows: list = field(default_factory=list)

    @property
    def done(self):
        return sum(1 for row in self.rows if row.is_filled)


def answers(revision):
    """Сохранённые ответы ревизии: ``{группа: {название: запись}}``.

    Приводит к ожидаемому виду и отбрасывает то, что в него не укладывается:
    JSON правят руками и в psql, и в админке, и один кривой ключ не должен
    ронять карточку — чек-лист не то, ради чего на неё заходят. Пустое поле,
    ``None`` и мусор дают один и тот же ответ: пустой словарь.
    """
    stored = revision.checklist
    if not isinstance(stored, dict):
        return {}
    return {group: {title: entry for title, entry in titles.items()
                    if isinstance(entry, dict)}
            for group, titles in stored.items()
            if isinstance(titles, dict)}


def rows_for(revision):
    """Все строки чек-листов ревизии: шаблонные и пришедшие со страниц.

    Порядок — шаблона, а не базы: сравнивать готовность двух ревизий можно,
    только когда строки стоят одинаково.
    """
    stored = answers(revision)
    rows = []

    for group, title, responsibility, hint, file_format in TEMPLATE:
        saved = (stored.get(group) or {}).get(title) or {}
        rows.append(Row(
            group=group, title=title, responsibility=responsibility,
            hint=hint, file_format=file_format,
            status=saved.get("status", ""),
            comment=saved.get("comment", ""),
            url=saved.get("url", "")))

    for group, titles in stored.items():
        for title, saved in titles.items():
            if (group, title) in TEMPLATE_KEYS:
                continue
            rows.append(Row(
                group=group, title=title,
                responsibility=saved.get("responsibility", ""),
                hint=saved.get("hint", ""),
                file_format=saved.get("file_format", ""),
                status=saved.get("status", ""),
                comment=saved.get("comment", ""),
                url=saved.get("url", ""),
                extra=True))
    return rows


def by_group(rows):
    """Раскладывает строки по чек-листам — в порядке GROUPS."""
    order = {group: index for index, (group, _, _) in enumerate(GROUPS)}
    names = {group: (title, short) for group, title, short in GROUPS}

    grouped = {}
    for row in rows:
        grouped.setdefault(row.group, []).append(row)

    return [Group(group=group,
                  title=names.get(group, (group, group))[0],
                  short=names.get(group, (group, group))[1],
                  rows=found)
            for group, found in sorted(grouped.items(),
                                       key=lambda pair: order.get(pair[0], 99))]


def groups_for(revision):
    """Готовые к показу чек-листы ревизии."""
    return by_group(rows_for(revision))


def progress(revision):
    """``(заполнено, всего)`` — для счётчика в шапке карточки."""
    rows = rows_for(revision)
    return sum(1 for row in rows if row.is_filled), len(rows)


def _without_empty(values):
    """Пустые ключи в записи не держим: место занимают, смысла не несут."""
    return {name: value for name, value in values.items() if value}


def save_answers(revision, updates, commit=True):
    """Записывает ответы: ``{(группа, название): {status, comment, url}}``.

    Описание документа не трогается: у строк вне шаблона оно лежит в той же
    записи, и затирать его ответами нельзя.
    """
    stored = {group: dict(titles)
              for group, titles in answers(revision).items()}

    for (group, title), values in updates.items():
        rows = stored.get(group) or {}
        entry = dict(rows.get(title) or {})
        entry.update({name: values.get(name, "") for name in ANSWER_KEYS})
        entry = _without_empty(entry)

        if entry:
            rows[title] = entry
        else:
            rows.pop(title, None)

        if rows:
            stored[group] = rows
        else:
            stored.pop(group, None)

    revision.checklist = stored
    if commit:
        revision.save(update_fields=["checklist"])
    return stored


def describe(revision, group, title, description, commit=False):
    """Кладёт описание строки, которой нет в шаблоне.

    Заполняет только пустое: описание могли поправить руками, а страницы
    Confluence перезаливают. Для строк шаблона ничего не делает — у них
    описание в коде, и хранить его копию значило бы завести второй источник
    правды.
    """
    if (group, title) in TEMPLATE_KEYS:
        return revision.checklist

    stored = {existing: dict(titles)
              for existing, titles in answers(revision).items()}
    rows = stored.get(group) or {}
    entry = dict(rows.get(title) or {})

    for name in DESCRIPTION_KEYS:
        value = description.get(name) or ""
        if value and not entry.get(name):
            entry[name] = value

    rows[title] = entry
    stored[group] = rows
    revision.checklist = stored
    if commit:
        revision.save(update_fields=["checklist"])
    return stored
