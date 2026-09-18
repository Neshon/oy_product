"""Реестр категорий компонентов.

Одна точка, из которой берут данные и веб-интерфейс, и админка:
какие модели показывать, какие колонки выводить в таблице,
что доступно только для чтения.

Категории собираются один раз при импорте модуля. Всё, что зависит только
от модели — набор колонок, фильтры, подписи, — считается тогда же и дальше
просто читается: раньше это пересчитывалось по нескольку раз на запрос.
"""

from dataclasses import dataclass, field
from typing import Type

from django.db.models import Model

from . import models as m
from .db import unavailable
from .mixins import field_names

# колонки, общие для списка любой группы: первая из них — основная,
# по ней строка опознаётся и она же ведёт на карточку
BASE_COLUMNS = ["vendor_pn", "oy_id", "gbt_pn", "description", "vendor", "package"]

# замыкают строку: в таблицах замен этих полей нет, и они просто не выведутся
TAIL_COLUMNS = ["allegro_schematic_part", "allegro_pcb_footprint"]

# Порядок полей для карточки и выгрузки.
#
# Общие поля объявлены в абстрактном классе, поэтому в ``_meta.fields`` они
# идут раньше полей группы — не в том порядке, в каком колонки лежат в базе.
# Для показа порядок задан здесь явно: сначала то, чем компонент опознают,
# затем служебное, затем параметры группы и последним — суррогатный ключ.
LEAD_FIELDS = (
    "vendor_pn", "oy_pn", "oy_id", "gbt_pn", "group", "subgroup",
    "description", "vendor", "country", "smt_tht", "package", "packaging",
    "pb_no_pb", "datasheet", "tracker_url",
    "allegro_schematic_part", "allegro_pcb_footprint",
    "author", "created", "status", "notice",
)


def ordered_fields(model):
    """Поля модели в порядке показа: см. :data:`LEAD_FIELDS`."""
    rest = {f.name: f for f in model._meta.fields}
    lead = [rest.pop(name) for name in LEAD_FIELDS if name in rest]
    pk = rest.pop(model._meta.pk.name, None)
    # остаток — параметры группы, в порядке объявления в модели
    return lead + list(rest.values()) + ([pk] if pk is not None else [])


@dataclass(frozen=True)
class Category:
    slug: str            # используется в URL, совпадает с model_name
    model: Type[Model]
    title: str           # человеческое название
    table: str           # имя таблицы в PostgreSQL
    extra_columns: tuple = ()
    skip_columns: tuple = ()
    filter_fields: tuple = ()
    read_only: bool = False
    replacement: bool = False

    # ниже — вычисляется в __post_init__, извне не задаётся
    columns: tuple = field(default=(), init=False)
    verbose_columns: tuple = field(default=(), init=False)
    filters: tuple = field(default=(), init=False)
    all_field_names: tuple = field(default=(), init=False)
    # собственные поля модели: набор нужен почти всем обходам таблиц,
    # и раньше каждый из них собирал его сам
    field_names: frozenset = field(default=frozenset(), init=False)
    pk_name: str = field(default="", init=False)

    def __post_init__(self):
        meta = self.model._meta
        names = {f.name for f in meta.get_fields()}
        own = field_names(self.model)

        columns = [c for c in BASE_COLUMNS
                   if c in names and c not in self.skip_columns]
        columns += [c for c in self.extra_columns if c in names]
        columns += [c for c in TAIL_COLUMNS
                    if c in names and c not in self.skip_columns]

        # dataclass заморожен, поэтому вычисленное проставляется в обход
        self._set("columns", tuple(columns))
        self._set("verbose_columns",
                  tuple((n, meta.get_field(n).verbose_name) for n in columns))
        self._set("filters",
                  tuple((n, meta.get_field(n).verbose_name)
                        for n in self.filter_fields if n in own))
        self._set("all_field_names",
                  tuple(f.name for f in ordered_fields(self.model)))
        self._set("field_names", own)
        self._set("pk_name", meta.pk.name)

    def available(self, fields):
        """Из перечисленных полей — те, что есть в этой таблице."""
        return [name for name in fields if name in self.field_names]

    def _set(self, name, value):
        object.__setattr__(self, name, value)

    @property
    def ordered_fields(self):
        """Поля модели в порядке показа — для карточки и выгрузки."""
        return ordered_fields(self.model)


# Фильтры над списком — свои для каждой группы. Таблицы замен берут набор
# у своей рабочей таблицы: слаг у них тот же плюс суффикс.
FILTER_FIELDS = {
    "capacitor": ("vendor", "subgroup", "smt_tht", "package", "value",
                  "voltage_v", "tolerance", "dielectric_type"),
    "clock": ("vendor", "subgroup", "smt_tht", "value", "frequency_tolerance"),
    "connector": ("vendor", "subgroup", "smt_tht", "connector_type", "interface",
                  "number_of_pins", "number_of_rows", "pitch"),
    "diode": ("vendor", "subgroup", "smt_tht", "package", "forward_voltage_v"),
    "fuse": ("vendor", "subgroup", "smt_tht", "package", "value_a", "voltage_v"),
    "ic": ("vendor", "subgroup", "smt_tht", "package"),
    "indicator": ("vendor", "subgroup", "smt_tht", "package", "color",
                  "forward_voltage_v"),
    "inductor": ("vendor", "subgroup", "smt_tht", "package", "value",
                 "tolerance", "dc_resistance_ohm"),
    "mechanical": ("vendor", "subgroup", "smt_tht"),
    "pcb": (),
    "poweric": ("vendor", "subgroup", "smt_tht", "package", "input_voltage_v",
                "output_voltage_v", "output_current_a"),
    "resistor": ("vendor", "subgroup", "smt_tht", "package", "value",
                 "tolerance", "voltage_v", "power_dissipation_w"),
    "switch": ("vendor", "subgroup", "smt_tht"),
    "transistor": ("vendor", "subgroup", "smt_tht", "package"),
}

# колонки из общего набора, которые в отдельных группах не нужны
SKIP_COLUMNS = {
    "pcb": ("vendor", "package"),
}

EXTRA_COLUMNS = {
    "capacitor": ("value", "voltage_v", "dielectric_type", "tolerance"),
    "clock": ("value", "frequency_tolerance"),
    "connector": ("connector_type", "interface", "number_of_pins", "pitch"),
    "diode": ("forward_voltage_v",),
    "fuse": ("value_a", "voltage_v"),
    "ic": ("subgroup",),
    "indicator": ("color", "forward_voltage_v"),
    "inductor": ("value", "rated_current_a", "dc_resistance_ohm"),
    "mechanical": ("dimensions_mm",),
    "pcb": (),
    "poweric": ("input_voltage_v", "output_voltage_v", "output_current_a"),
    "resistor": ("value", "tolerance", "power_dissipation_w", "voltage_v"),
    "switch": ("lines_qty", "rated_voltage"),
    "transistor": ("subgroup",),
}

# чем слаг таблицы замен отличается от слага её рабочей таблицы
REPLACEMENT_SUFFIX = "replacement"


def _category(model, settings_key, replacement):
    """Категория. Настройки колонок таблица замен берёт у своей рабочей."""
    return Category(
        slug=model._meta.model_name,
        model=model,
        title=str(model._meta.verbose_name_plural),
        table=model._meta.db_table,
        extra_columns=EXTRA_COLUMNS.get(settings_key, ()),
        skip_columns=SKIP_COLUMNS.get(settings_key, ()),
        filter_fields=FILTER_FIELDS.get(settings_key, ()),
        replacement=replacement,
    )


def _build():
    categories = {}
    for model in m.MAIN_MODELS:
        slug = model._meta.model_name
        categories[slug] = _category(model, slug, replacement=False)
    for model in m.REPLACEMENT_MODELS:
        slug = model._meta.model_name
        categories[slug] = _category(model, slug.removesuffix(REPLACEMENT_SUFFIX),
                                     replacement=True)
    # Представление Parts здесь намеренно отсутствует: это объект уровня
    # PostgreSQL, с которым работает другой софт, и Django его не касается.
    return categories


CATEGORIES = _build()

MAIN_CATEGORIES = [c for c in CATEGORIES.values() if not c.replacement]
REPLACEMENT_CATEGORIES = [c for c in CATEGORIES.values() if c.replacement]

CATEGORY_BY_TABLE = {c.table: c for c in CATEGORIES.values()}


def get_category(slug):
    return CATEGORIES.get(slug)


def category_by_table(table):
    """Категория по имени таблицы в базе — так строки BOM находят свою модель."""
    return CATEGORY_BY_TABLE.get(table)


def counterpart(category):
    """Парная категория: для рабочей группы — её замены, для замен — оригиналы.

    Слаги устроены симметрично (``capacitor`` ↔ ``capacitorreplacement``),
    поэтому пара выводится из имени. Для PCB таблицы замен нет — вернётся None.
    """
    if category is None:
        return None
    if category.replacement:
        return CATEGORIES.get(category.slug.removesuffix(REPLACEMENT_SUFFIX))
    return CATEGORIES.get(category.slug + REPLACEMENT_SUFFIX)


# сколько строк база отдаёт за раз при полном обходе таблицы
SCAN_CHUNK = 2000


def scan(fields, require=("id",), categories=None, failed=None,
         chunk_size=SCAN_CHUNK):
    """Читает выбранные колонки из всех таблиц компонентов.

    Отдаёт пары ``(категория, {поле: значение})``. Так устроены три обхода,
    которые раньше повторяли друг друга слово в слово: отчёт по дублям,
    индекс артикулов для BOM и индекс для импорта ссылок.

    Строки берутся потоком (``iterator``), а не списком: в таблицах
    компонентов их десятки тысяч, и держать в памяти сразу всё незачем —
    вызывающему нужно ровно то, что он успел из строки взять.

    Таблица пропускается, если в ней нет полей из ``require``. Недоступная
    таблица не роняет обход: её имя попадает в ``failed``, если список
    передали.
    """
    for category in (categories if categories is not None
                     else CATEGORIES.values()):
        available = category.available(fields)
        if not set(require) <= set(available):
            continue
        with unavailable(category.table, failed):
            rows = (category.model.objects
                    # order_by() снимает Meta.ordering: сортировать полный
                    # обход не нужно, а базе это лишний проход по данным
                    .order_by()
                    .values_list(*available)
                    .iterator(chunk_size=chunk_size))
            for row in rows:
                yield category, dict(zip(available, row))
