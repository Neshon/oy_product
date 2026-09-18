"""Модели библиотеки компонентов.

Модели описывают **существующую** схему PostgreSQL: все они помечены
``managed = False``, Django не создаёт и не изменяет эти таблицы
миграциями, а только читает и пишет данные.

Имена колонок в БД содержат пробелы, запятые и символ °, поэтому у каждого
поля явно указан ``db_column``. До миграции ``sql/rename_double_space_columns.sql``
эти имена были неодинаковы от таблицы к таблице (``Dimensions, mm`` в одних
и ``Dimensions,  mm`` в других, аналогично с ``Height`` и ``Temperature``);
теперь все таблицы приведены к единому написанию — «Название, единица»,
как и у остальных однотипных колонок (``Voltage, V``, ``Value, A``).

Почти все колонки описаны одинаково: ``varchar(255)``, необязательные, с
подписью, совпадающей с именем колонки. Поэтому поля объявляются через
:func:`text` и :func:`long_text` — в строке остаётся только то, чем поля
различаются, то есть само имя колонки.

Каждая таблица описана своим классом целиком, даже когда набор параметров
у рабочей таблицы и у её замен совпадает слово в слово. Схему ведём не мы,
и список колонок должен читаться рядом с именем таблицы, а не собираться
из общих примесей: общее вынесено только там, где оно общее по смыслу
(:class:`BaseComponent`, :class:`AllegroFields`, :class:`PhysicalFields`),
а не там, где два набора параметров пока случайно совпали.

Структура файла:

* :class:`BaseComponent` — 19 полей, одинаковых во всех 27 таблицах,
  плюс общее поведение (поиск, сохранение, ссылка на карточку);
* :class:`AllegroFields` — пара полей САПР, которая есть только в рабочих
  таблицах; в таблицах замен этих колонок нет;
* :class:`PhysicalFields` — габариты и рабочая температура; есть везде,
  кроме PCB (у платы этих параметров в базе нет);
* по классу на таблицу — только те поля, что свойственны группе;
* :data:`MAIN_MODELS` и :data:`REPLACEMENT_MODELS` — списки, из которых
  реестр собирает категории.

Порядок полей в ``_meta.fields`` после наследования отличается от порядка
колонок в БД, поэтому для показа и выгрузки он задаётся явно —
см. ``components.registry.ordered_fields``.
"""

from django.db import models
from django.urls import reverse

from .mixins import ComponentQuerySet, ComponentSaveMixin
from .refs import ComponentRefMixin


def text(column, verbose_name=None):
    """Колонка ``varchar(255)`` — так описано подавляющее большинство полей.

    Подпись по умолчанию совпадает с именем колонки: в интерфейсе поля
    называются так же, как в базе, и расходиться им незачем.
    """
    return models.CharField(db_column=column, max_length=255, blank=True,
                            null=True, verbose_name=verbose_name or column)


def long_text(column, verbose_name=None):
    """То же для ``text``: у описаний и примечаний длина не ограничена."""
    return models.TextField(db_column=column, blank=True, null=True,
                            verbose_name=verbose_name or column)


class BaseComponent(ComponentSaveMixin, models.Model):
    """Поля и поведение, общие для всех 27 таблиц компонентов."""

    objects = ComponentQuerySet.as_manager()

    vendor_pn = text("Vendor PN")
    oy_pn = text("OY PN")
    oy_id = text("OY ID")
    gbt_pn = text("GBT PN")
    group = text("Group")
    subgroup = text("Subgroup")
    description = long_text("Description")
    vendor = text("Vendor")
    country = text("Country")
    smt_tht = text("SMT_THT")
    package = text("Package")
    packaging = text("Packaging")
    pb_no_pb = text("Pb_No Pb")
    datasheet = text("Datasheet")
    # Ссылка на задачу трекера. Раньше такие ссылки лежали в отдельной
    # таблице oy_component_link: колонки под них в исходной схеме не было,
    # а заводить её в 27 чужих таблицах не хотелось. Практика показала, что
    # ссылка у компонента одна и ведёт себя как обычный параметр — поэтому
    # колонка добавлена в сами таблицы (sql/add_tracker_url.sql), а
    # отдельная таблица удалена.
    tracker_url = text("Tracker URL", "Ссылка на Tracker")
    author = text("Author")
    created = models.DateTimeField(db_column="Created", blank=True,
                                   null=True, verbose_name="Created")
    status = text("Status")
    notice = long_text("Notice")
    id = models.AutoField(primary_key=True, verbose_name="id")

    class Meta:
        abstract = True

    def __str__(self):
        return self.display_title()

    def display_title(self):
        return self.vendor_pn or self.oy_pn or self.description or f"#{self.pk}"

    def get_absolute_url(self):
        return reverse("components:detail",
                       args=[self._meta.model_name, self.pk])


class AllegroFields(models.Model):
    """Файлы САПР Allegro. В таблицах замен этих колонок нет."""

    allegro_schematic_part = text("Allegro Schematic Part")
    allegro_pcb_footprint = text("Allegro PCB Footprint")

    class Meta:
        abstract = True


class PhysicalFields(models.Model):
    """Габариты и рабочая температура. Есть у всех таблиц, кроме PCB —
    у платы эти параметры не заполняются, колонок для них в базе нет."""

    dimensions_mm = text("Dimensions, mm")
    height_mm = text("Height, mm")
    temperature_min_c = text("Temperature min, °C")
    temperature_max_c = text("Temperature max, °C")

    class Meta:
        abstract = True


class Capacitor(AllegroFields, PhysicalFields, BaseComponent):
    value = text("Value")
    value_f_si = text("Value, F (SI)")
    tolerance = text("Tolerance")
    voltage_v = text("Voltage, V")
    dielectric_type = text("Dielectric type")
    polarity = text("Polarity")
    esr = text("ESR")
    spice = text("SPICE")
    ibis = text("IBIS")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "CAPACITOR"
        verbose_name = "Конденсатор"
        verbose_name_plural = "Конденсаторы"
        ordering = ["-id"]


class Clock(AllegroFields, PhysicalFields, BaseComponent):
    value = text("Value")
    frequency_tolerance = text("Frequency Tolerance")
    operating_mode = text("Operating mode")
    spice = text("SPICE")
    ibis = text("IBIS")

    class Meta:
        managed = False
        db_table = "CLOCK"
        verbose_name = "Генератор/резонатор"
        verbose_name_plural = "Генераторы и резонаторы"
        ordering = ["-id"]


class Connector(AllegroFields, PhysicalFields, BaseComponent):
    connector_type = text("Connector type")
    interface = text("Interface")
    number_of_pins = text("Number of Pins")
    number_of_rows = text("Number of Rows")
    pitch = text("Pitch")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "CONNECTOR"
        verbose_name = "Разъём"
        verbose_name_plural = "Разъёмы"
        ordering = ["-id"]


class Diode(AllegroFields, PhysicalFields, BaseComponent):
    forward_voltage_v = text("Forward Voltage, V")
    ibis = text("IBIS")
    s_parameters = text("S-parameters")
    spice = text("SPICE")

    class Meta:
        managed = False
        db_table = "DIODE"
        verbose_name = "Диод"
        verbose_name_plural = "Диоды"
        ordering = ["-id"]


class Fuse(AllegroFields, PhysicalFields, BaseComponent):
    value_a = text("Value, A")
    voltage_v = text("Voltage, V")
    ibis = text("IBIS")
    spice = text("SPICE")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "FUSE"
        verbose_name = "Предохранитель"
        verbose_name_plural = "Предохранители"
        ordering = ["-id"]


class IC(AllegroFields, PhysicalFields, BaseComponent):
    ibis = text("IBIS")
    spice = text("SPICE")

    class Meta:
        managed = False
        db_table = "IC"
        verbose_name = "Микросхема"
        verbose_name_plural = "Микросхемы"
        ordering = ["-id"]


class Indicator(AllegroFields, PhysicalFields, BaseComponent):
    color = text("Color")
    forward_voltage_v = text("Forward Voltage, V")
    spice = text("SPICE")

    class Meta:
        managed = False
        db_table = "INDICATOR"
        verbose_name = "Индикатор"
        verbose_name_plural = "Индикаторы"
        ordering = ["-id"]


class Inductor(AllegroFields, PhysicalFields, BaseComponent):
    impedance_ohm = text("Impedance, Ohm")
    dc_resistance_ohm = text("DC Resistance, Ohm")
    rated_current_a = text("Rated current, A")
    value = text("Value")
    value_h_si = text("Value, H (SI)")
    tolerance = text("Tolerance")
    ibis = text("IBIS")
    spice = text("SPICE")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "INDUCTOR"
        verbose_name = "Индуктивность"
        verbose_name_plural = "Индуктивности"
        ordering = ["-id"]


class Mechanical(AllegroFields, PhysicalFields, BaseComponent):
    material = text("Material")

    class Meta:
        managed = False
        db_table = "MECHANICAL"
        verbose_name = "Механика"
        verbose_name_plural = "Механика"
        ordering = ["-id"]


class PCB(AllegroFields, BaseComponent):
    """Своих параметров у группы нет — только общие поля."""

    class Meta:
        managed = False
        db_table = "PCB"
        verbose_name = "Печатная плата"
        verbose_name_plural = "Печатные платы"
        ordering = ["-id"]


class PowerIC(AllegroFields, PhysicalFields, BaseComponent):
    input_voltage_v = text("Input Voltage, V")
    output_voltage_v = text("Output Voltage, V")
    output_current_a = text("Output Current, A")
    ibis = text("IBIS")
    spice = text("SPICE")

    class Meta:
        managed = False
        db_table = "POWER_IC"
        verbose_name = "Силовая микросхема"
        verbose_name_plural = "Силовые микросхемы"
        ordering = ["-id"]


class Resistor(AllegroFields, PhysicalFields, BaseComponent):
    value = text("Value")
    value_ohm_si = text("Value, Ohm (SI)")
    tolerance = text("Tolerance")
    voltage_v = text("Voltage, V")
    power_dissipation_w = text("Power dissipation, W")
    spice = text("SPICE")
    resistor_quantity = text("Resistor quantity")
    ibis = text("IBIS")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "RESISTOR"
        verbose_name = "Резистор"
        verbose_name_plural = "Резисторы"
        ordering = ["-id"]


class Switch(AllegroFields, PhysicalFields, BaseComponent):
    lines_qty = text("Lines QTY")
    rated_voltage = text("Rated Voltage")

    class Meta:
        managed = False
        db_table = "SWITCH"
        verbose_name = "Переключатель"
        verbose_name_plural = "Переключатели"
        ordering = ["-id"]


class Transistor(AllegroFields, PhysicalFields, BaseComponent):
    ibis = text("IBIS")
    spice = text("SPICE")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "TRANSISTOR"
        verbose_name = "Транзистор"
        verbose_name_plural = "Транзисторы"
        ordering = ["-id"]


class CapacitorReplacement(PhysicalFields, BaseComponent):
    value = text("Value")
    value_f_si = text("Value, F (SI)")
    tolerance = text("Tolerance")
    voltage_v = text("Voltage, V")
    dielectric_type = text("Dielectric type")
    polarity = text("Polarity")
    esr = text("ESR")
    ibis = text("IBIS")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "z_CAPACITOR"
        verbose_name = "Конденсатор (замена)"
        verbose_name_plural = "Конденсаторы (замены)"
        ordering = ["-id"]


class ClockReplacement(PhysicalFields, BaseComponent):
    value = text("Value")
    frequency_tolerance = text("Frequency Tolerance")
    operating_mode = text("Operating mode")
    ibis = text("IBIS")

    class Meta:
        managed = False
        db_table = "z_CLOCK"
        verbose_name = "Генератор/резонатор (замена)"
        verbose_name_plural = "Генераторы и резонаторы (замены)"
        ordering = ["-id"]


class ConnectorReplacement(PhysicalFields, BaseComponent):
    connector_type = text("Connector type")
    interface = text("Interface")
    number_of_pins = text("Number of Pins")
    number_of_rows = text("Number of Rows")
    pitch = text("Pitch")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "z_CONNECTOR"
        verbose_name = "Разъём (замена)"
        verbose_name_plural = "Разъёмы (замены)"
        ordering = ["-id"]


class DiodeReplacement(PhysicalFields, BaseComponent):
    forward_voltage_v = text("Forward Voltage, V")
    ibis = text("IBIS")
    s_parameters = text("S-parameters")
    spice = text("SPICE")

    class Meta:
        managed = False
        db_table = "z_DIODE"
        verbose_name = "Диод (замена)"
        verbose_name_plural = "Диоды (замены)"
        ordering = ["-id"]


class FuseReplacement(PhysicalFields, BaseComponent):
    value_a = text("Value, A")
    voltage_v = text("Voltage, V")
    ibis = text("IBIS")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "z_FUSE"
        verbose_name = "Предохранитель (замена)"
        verbose_name_plural = "Предохранители (замены)"
        ordering = ["-id"]


class ICReplacement(PhysicalFields, BaseComponent):
    ibis = text("IBIS")
    spice = text("SPICE")

    class Meta:
        managed = False
        db_table = "z_IC"
        verbose_name = "Микросхема (замена)"
        verbose_name_plural = "Микросхемы (замены)"
        ordering = ["-id"]


class IndicatorReplacement(PhysicalFields, BaseComponent):
    color = text("Color")
    forward_voltage_v = text("Forward Voltage, V")

    class Meta:
        managed = False
        db_table = "z_INDICATOR"
        verbose_name = "Индикатор (замена)"
        verbose_name_plural = "Индикаторы (замены)"
        ordering = ["-id"]


class InductorReplacement(PhysicalFields, BaseComponent):
    impedance_ohm = text("Impedance, Ohm")
    dc_resistance_ohm = text("DC Resistance, Ohm")
    rated_current_a = text("Rated current, A")
    value = text("Value")
    value_h_si = text("Value, H (SI)")
    tolerance = text("Tolerance")
    ibis = text("IBIS")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "z_INDUCTOR"
        verbose_name = "Индуктивность (замена)"
        verbose_name_plural = "Индуктивности (замены)"
        ordering = ["-id"]


class MechanicalReplacement(PhysicalFields, BaseComponent):
    material = text("Material")

    class Meta:
        managed = False
        db_table = "z_MECHANICAL"
        verbose_name = "Механика (замена)"
        verbose_name_plural = "Механика (замены)"
        ordering = ["-id"]


class PowerICReplacement(PhysicalFields, BaseComponent):
    input_voltage_v = text("Input Voltage, V")
    output_voltage_v = text("Output Voltage, V")
    output_current_a = text("Output Current, A")
    ibis = text("IBIS")
    spice = text("SPICE")

    class Meta:
        managed = False
        db_table = "z_POWER_IC"
        verbose_name = "Силовая микросхема (замена)"
        verbose_name_plural = "Силовые микросхемы (замены)"
        ordering = ["-id"]


class ResistorReplacement(PhysicalFields, BaseComponent):
    value = text("Value")
    value_ohm_si = text("Value, Ohm (SI)")
    tolerance = text("Tolerance")
    voltage_v = text("Voltage, V")
    power_dissipation_w = text("Power dissipation, W")
    resistor_quantity = text("Resistor quantity")
    ibis = text("IBIS")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "z_RESISTOR"
        verbose_name = "Резистор (замена)"
        verbose_name_plural = "Резисторы (замены)"
        ordering = ["-id"]


class SwitchReplacement(PhysicalFields, BaseComponent):
    lines_qty = text("Lines QTY")
    rated_voltage = text("Rated Voltage")

    class Meta:
        managed = False
        db_table = "z_SWITCH"
        verbose_name = "Переключатель (замена)"
        verbose_name_plural = "Переключатели (замены)"
        ordering = ["-id"]


class TransistorReplacement(PhysicalFields, BaseComponent):
    ibis = text("IBIS")
    s_parameters = text("S-parameters")

    class Meta:
        managed = False
        db_table = "z_TRANSISTOR"
        verbose_name = "Транзистор (замена)"
        verbose_name_plural = "Транзисторы (замены)"
        ordering = ["-id"]


MAIN_MODELS = [
    Capacitor,
    Clock,
    Connector,
    Diode,
    Fuse,
    IC,
    Indicator,
    Inductor,
    Mechanical,
    PCB,
    PowerIC,
    Resistor,
    Switch,
    Transistor,
]

REPLACEMENT_MODELS = [
    CapacitorReplacement,
    ClockReplacement,
    ConnectorReplacement,
    DiodeReplacement,
    FuseReplacement,
    ICReplacement,
    IndicatorReplacement,
    InductorReplacement,
    MechanicalReplacement,
    PowerICReplacement,
    ResistorReplacement,
    SwitchReplacement,
    TransistorReplacement,
]


class OptionField(models.Model):
    """Столбец, значения которого выбираются из списка.

    Задаёт, какое поле превращается в выпадающий список и в каких таблицах
    это работает. Сами значения — в OptionValue.
    """

    field = models.CharField(
        max_length=64, verbose_name="Столбец",
        help_text="Имя поля модели, например smt_tht. Один столбец можно "
                  "завести несколько раз — с разными наборами таблиц")
    label = models.CharField(
        max_length=128, blank=True, default="", verbose_name="Название",
        help_text="Как столбец называть в интерфейсе. Пусто — как в базе")
    tables = models.JSONField(
        default=list, blank=True, verbose_name="Таблицы",
        help_text="В каких таблицах работает список. Пусто — во всех")
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    class Meta:
        db_table = "oy_option_field"
        ordering = ("field", "id")
        verbose_name = "Выпадающий список"
        verbose_name_plural = "Столбцы со списками"

    def __str__(self):
        return self.label or self.field

    def applies_to(self, table):
        """Пустой список таблиц означает «во всех»."""
        return not self.tables or table in self.tables


class OptionValue(models.Model):
    """Значение выпадающего списка.

    В записях компонентов по-прежнему хранится строка, поэтому удаление
    значения отсюда убирает его только из списка выбора. Для этого есть
    is_active: отключить обычно правильнее, чем удалить.
    """

    option_field = models.ForeignKey(
        OptionField, on_delete=models.CASCADE, related_name="values",
        verbose_name="Столбец")
    value = models.CharField(max_length=255, verbose_name="Значение")
    is_active = models.BooleanField(default=True, verbose_name="Активно")

    class Meta:
        db_table = "oy_option_value"
        ordering = ("option_field", "value")
        unique_together = ("option_field", "value")
        verbose_name = "Значение"
        verbose_name_plural = "Значения"

    def __str__(self):
        return self.value


class ComponentChange(ComponentRefMixin, models.Model):
    """Запись в истории изменений компонента.

    Таблицы компонентов неуправляемые, добавлять в 27 чужих таблиц колонки
    под историю нельзя — да и история к одной записи не сводится. Поэтому
    она лежит отдельно и ссылается на компонент так же, как ссылки и строки
    BOM: именем таблицы и ключом записи.

    Что именно поменялось, хранится в ``changes`` — списком, по словарю на
    каждое поле: имя, подпись, старое значение и новое. Значения кладутся
    строками, какими их видел пользователь: история должна остаться
    читаемой, даже если поле потом переименуют или уберут из модели.

    У записи о дубле список устроен иначе: там не поля, а записи, с
    которыми совпало, — таблица, ключ, название и сработавшее правило.
    Разбирается это по ``action``.

    Как и у ссылок, внешнего ключа здесь быть не может. Компонент удалят —
    записи истории останутся; это осознанно: «кто и когда правил» бывает
    нужно и после удаления. Собственно удаление тоже попадает в историю,
    и увидеть его можно только здесь: карточки у удалённой записи больше
    нет. Список — в админке, раздел «История изменений».
    """

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    DUPLICATE = "duplicate"
    ACTIONS = [
        (CREATED, "Добавлен"),
        (UPDATED, "Изменён"),
        (DELETED, "Удалён"),
        # заведён при том, что похожая запись уже была, и человек это
        # подтвердил: событие само по себе, отдельно от заведения
        (DUPLICATE, "Добавлен как дубль"),
    ]

    component_table = models.CharField(
        max_length=64, verbose_name="Таблица компонента")
    component_id = models.IntegerField(verbose_name="Ключ компонента")
    author = models.CharField(max_length=150, blank=True, default="",
                              verbose_name="Кто")
    created = models.DateTimeField(auto_now_add=True, verbose_name="Когда")
    action = models.CharField(max_length=16, choices=ACTIONS, default=UPDATED,
                              verbose_name="Что произошло")
    source = models.CharField(
        max_length=32, blank=True, default="", verbose_name="Откуда",
        help_text="Через сайт или через админку")
    changes = models.JSONField(
        default=list, blank=True, verbose_name="Что поменялось",
        help_text="Список полей: имя, подпись, старое значение, новое")

    class Meta:
        db_table = "oy_component_change"
        # новые сверху: в карточке нужны последние правки
        ordering = ("-created", "-id")
        verbose_name = "Изменение компонента"
        verbose_name_plural = "История изменений"
        indexes = [
            models.Index(fields=["component_table", "component_id",
                                 "-created"],
                         name="component_change_target_idx"),
        ]

    def __str__(self):
        return f"{self.author or 'неизвестно'} · {self.created:%d.%m.%Y %H:%M}"

    @property
    def fields_count(self):
        return len(self.changes or [])

    # Короткие подписи для списка в карточке: он стоит в узкой колонке, и
    # «Добавлен как дубль» там переносится на две строки. На странице правки
    # подпись остаётся полной — места хватает.
    SHORT_ACTIONS = {CREATED: "добавлен", UPDATED: "изменён",
                     DELETED: "удалён", DUPLICATE: "дубль"}

    # цвет чипа в списке — по событию. Держим рядом с подписями: и то, и
    # другое зависит от action, и разъезжаться им незачем
    CHIP_CLASSES = {CREATED: "chip--added", UPDATED: "chip--edited",
                    DELETED: "chip--gone", DUPLICATE: "chip--dup"}

    @property
    def short_action(self):
        return self.SHORT_ACTIONS.get(self.action, self.action)

    @property
    def chip_class(self):
        return self.CHIP_CLASSES.get(self.action, "")

    @property
    def is_duplicate(self):
        """У дубля другой состав ``changes`` — шаблон показывает его иначе."""
        return self.action == self.DUPLICATE
