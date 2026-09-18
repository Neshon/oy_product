"""Серверы и их состав.

Раздел называется по верхнему уровню — сервер, — но заведено в нём всё,
из чего сервер собран. Позиция (:class:`Item`) — это сервер, узел, плата,
кабель, корпус или материал: одна таблица на все уровни, потому что
вложенность в производстве меняется, а «плата» сегодня может оказаться
узлом завтра. Вложенность живёт не в позиции, а в строках состава
(:class:`BomLine`): «в позицию A входит позиция B в количестве 2». Так одна
и та же плата стоит в трёх серверах, оставаясь одной записью, — при дереве
её пришлось бы завести трижды, и дальше расходились бы правки.

Получается ориентированный граф. Единственное жёсткое ограничение — узел не
должен попасть внутрь самого себя через любую глубину: иначе разузлование
однажды уйдёт в бесконечный цикл на боевых данных. Проверка — в
:meth:`BomLine.clean`.

Ревизий у позиций нет намеренно: состав живёт прямо на позиции, а история
пишется в журнал правок. Исключение — платы: у них ревизии уже есть и
работают (импорт BOM заводит ревизию, есть сравнение и переключение
текущей). Ломать это ради единообразия не стали, поэтому позиция-плата
своего состава не хранит: её состав — строки текущей ревизии. Обе стороны
сведены представлением ``bom_edge`` (см. миграцию 0002), и обход состава
разбираться в этом уже не обязан.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

# Единицы измерения. Кабель меряют метрами, текстолит площадью, компаунд
# граммами — целого количества, как у строк BOM платы, здесь не хватает.
UNITS = (
    ("шт", "шт"),
    ("м", "м"),
    ("мм", "мм"),
    ("м²", "м²"),
    ("кг", "кг"),
    ("г", "г"),
    ("л", "л"),
    ("компл", "компл"),
)


class ItemQuerySet(models.QuerySet):

    def search(self, term):
        """Поиск по номерам и названию."""
        term = (term or "").strip()
        if not term:
            return self
        return self.filter(
            models.Q(oy_pn__icontains=term)
            | models.Q(gct_pn__icontains=term)
            | models.Q(name__icontains=term)
            | models.Q(decimal_number__icontains=term))

    def with_counts(self):
        """Число строк состава — для списка, одним запросом."""
        return self.annotate(line_count=models.Count("lines", distinct=True))


class Item(models.Model):
    """Позиция: то, что имеет партномер и может во что-то входить."""

    SERVER = "server"
    ASSEMBLY = "assembly"
    BOARD = "board"
    CABLE = "cable"
    CHASSIS = "chassis"
    MECHANICAL = "mech"
    MATERIAL = "material"
    OTHER = "other"

    KINDS = (
        (SERVER, "Сервер"),
        (ASSEMBLY, "Узел"),
        (BOARD, "Плата"),
        (CABLE, "Кабель"),
        (CHASSIS, "Корпус"),
        (MECHANICAL, "Механика"),
        (MATERIAL, "Материал"),
        (OTHER, "Прочее"),
    )

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"
    STATUSES = (
        (DRAFT, "В разработке"),
        (ACTIVE, "В производстве"),
        (RETIRED, "Снята"),
    )

    oy_pn = models.CharField(max_length=255, unique=True, verbose_name="OY P/N")
    # Второй опознавательный номер. У механики из System BOM своего OY P/N
    # нет вовсе — только номер поставщика, и без этого поля половина такой
    # строки в базу не попадёт. Не уникален: у разных позиций он бывает
    # пустым, а пустых значений в БД может быть сколько угодно
    gct_pn = models.CharField(max_length=255, blank=True, default="",
                              db_index=True, verbose_name="GCT P/N")
    name = models.CharField(max_length=255, blank=True, default="",
                            verbose_name="Наименование")
    kind = models.CharField(max_length=16, choices=KINDS, default=ASSEMBLY,
                            db_index=True, verbose_name="Тип")
    status = models.CharField(max_length=16, choices=STATUSES, default=DRAFT,
                              verbose_name="Статус")
    decimal_number = models.CharField(max_length=128, blank=True, default="",
                                      verbose_name="Децимальный номер")
    description = models.TextField(blank=True, default="",
                                   verbose_name="Описание")
    owner = models.CharField(max_length=150, blank=True, default="",
                             verbose_name="Ответственный")

    # Остальные поля карточки — как есть, без своей колонки на каждое.
    # В выгрузке Confluence их 28 разных, набор у каждого типа свой и
    # меняется вместе с шаблоном страницы; заводить под это два десятка
    # колонок значит менять схему при каждой правке шаблона
    details = models.JSONField(default=dict, blank=True,
                               verbose_name="Поля карточки")

    # откуда приехала запись: страница Confluence или файл System BOM
    source = models.CharField(max_length=255, blank=True, default="",
                              verbose_name="Источник")

    # Плата ведётся в своём разделе: у неё ревизии, импорт BOM и сравнение.
    # Позиция на неё только ссылается, состав не дублирует
    board = models.OneToOneField("boards.Board", null=True, blank=True,
                                 on_delete=models.PROTECT,
                                 related_name="item", verbose_name="Плата")

    created = models.DateTimeField(auto_now_add=True, verbose_name="Заведена")
    updated = models.DateTimeField(auto_now=True, verbose_name="Изменена")

    objects = ItemQuerySet.as_manager()

    class Meta:
        ordering = ("kind", "oy_pn")
        verbose_name = "Позиция"
        verbose_name_plural = "Позиции"

    def __str__(self):
        return self.oy_pn

    def get_absolute_url(self):
        return reverse("servers:detail", args=[self.pk])

    @property
    def title(self):
        return self.name or self.oy_pn

    @property
    def is_board(self):
        return self.board_id is not None

    def own_lines(self):
        """Состав одного уровня — как он хранится.

        У платы состав лежит в её текущей ревизии, а не в BomLine, поэтому
        строки берутся оттуда. Возвращаются не объекты BomLine, а словари:
        вызывающему нужен один и тот же набор полей независимо от того,
        откуда состав пришёл.
        """
        if self.is_board:
            revision = self.board.current_revision
            if revision is None:
                return []
            return [
                {"oy_pn": item.oy_pn, "gct_pn": item.gbt_pn, "child": None,
                 "description": item.description, "quantity": item.qty or 1,
                 "unit": "шт", "position": item.position,
                 "designator": item.references, "comment": item.comment,
                 "line": None}
                for item in revision.items.filter(kind="M")
            ]
        return [
            {"oy_pn": line.oy_pn, "gct_pn": line.gct_pn, "child": line.child,
             "description": line.description, "quantity": line.quantity,
             "unit": line.unit, "position": line.position,
             "designator": line.designator, "comment": line.comment,
             "line": line}
            for line in self.lines.select_related("child")
        ]


class BomLine(models.Model):
    """Строка состава: что входит в позицию и сколько.

    Строка указывает либо на другую позицию (``child``), либо на компонент
    библиотеки по номеру. Внешним ключом второе не выразить: таблиц
    компонентов 27 и они неуправляемые — связь ставится так же, как в
    ``boards.BoardItem``, парой «таблица + ключ».
    """

    MAIN = "M"
    SUBSTITUTE = "S"
    KINDS = ((MAIN, "Основная"), (SUBSTITUTE, "Замена"))

    parent = models.ForeignKey(Item, on_delete=models.CASCADE,
                               related_name="lines", verbose_name="Позиция")
    position = models.IntegerField(null=True, blank=True,
                                   verbose_name="Позиция в составе")
    kind = models.CharField(max_length=1, choices=KINDS, default=MAIN,
                            verbose_name="Тип строки")

    # PROTECT: позицию, которая где-то применяется, нельзя удалить молча —
    # иначе состав изделия тихо обеднеет
    child = models.ForeignKey(Item, null=True, blank=True,
                              on_delete=models.PROTECT,
                              related_name="used_in", verbose_name="Входит")

    oy_pn = models.CharField(max_length=255, blank=True, default="",
                             verbose_name="OY P/N")
    gct_pn = models.CharField(max_length=255, blank=True, default="",
                              verbose_name="GCT P/N")
    description = models.TextField(blank=True, default="",
                                   verbose_name="Описание")

    # ссылка на запись библиотеки компонентов — как в boards.BoardItem
    component_table = models.CharField(max_length=64, blank=True, default="",
                                       verbose_name="Таблица компонента")
    component_id = models.IntegerField(null=True, blank=True,
                                       verbose_name="ID компонента")

    quantity = models.DecimalField(max_digits=12, decimal_places=3,
                                   default=Decimal("1"),
                                   verbose_name="Количество")
    unit = models.CharField(max_length=8, choices=UNITS, default="шт",
                            verbose_name="Ед. изм.")
    designator = models.TextField(blank=True, default="",
                                  verbose_name="Обозначение")
    comment = models.TextField(blank=True, default="",
                               verbose_name="Примечание")

    # Откуда строка взялась. Пустое — заведена руками; имя файла — импортом.
    # Повторный импорт заменяет только свои строки: без этого первая же
    # повторная заливка стёрла бы ручную работу
    source = models.CharField(max_length=255, blank=True, default="",
                              verbose_name="Источник")
    source_row = models.IntegerField(null=True, blank=True,
                                     verbose_name="Строка файла")

    class Meta:
        ordering = ("parent", "position", "kind", "id")
        verbose_name = "Строка состава"
        verbose_name_plural = "Строки состава"

    def __str__(self):
        return f"{self.parent_id}: {self.label} x {self.quantity}"

    @property
    def label(self):
        if self.child_id:
            return self.child.oy_pn
        return self.oy_pn or self.gct_pn or self.description or "—"

    @property
    def by_hand(self):
        return not self.source

    def clean(self):
        if not self.child_id and not (self.oy_pn or self.gct_pn
                                      or self.description):
            raise ValidationError(
                "Укажите вложенную позицию либо номер или описание.")

        if self.child_id and self.child_id == self.parent_id:
            raise ValidationError("Позиция не может входить сама в себя.")

        if self.child_id and self.parent_id:
            # Цикл через любую глубину: если родитель уже лежит внутри
            # дочерней позиции, то, добавив её сюда, мы замкнём кольцо
            from .tree import reaches

            if reaches(self.child_id, self.parent_id):
                raise ValidationError(
                    f"«{self.child}» уже содержит «{self.parent}» — "
                    f"получилось бы кольцо.")
