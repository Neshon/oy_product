"""Платы и их составы, полученные из BOM-файлов.

В отличие от таблиц компонентов, эти таблицы создаёт и ведёт Django:
их нет в исходной схеме, поэтому managed здесь по умолчанию.
"""

from django.db import models
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from components.matching import is_dash
from components.refs import ComponentRefMixin

from . import images
from .references import normalize_references, split_references
from .revisions import parse_pn, variant_of

# Поля шапки BOM. Список короткий, и это намеренно: остальное из шапки
# либо повторяло карточку, либо описывало файл, а не плату. «Old GCT BOM
# P/N» убран отдельно — им не пользовались, а даты и автора из файла мы не
# храним: строки «Дата загрузки BOM» и «Кто загрузил» значат другое.
#
# Правил заполнения два, и разница между ними существенная.
#
# Эти приходят только из файла, руками их не правят, поэтому каждая
# загрузка переписывает их целиком — включая стирание, если в новом файле
# значения не оказалось:
HEADER_FIELDS = ("previous_revision",)

# А эти есть и в карточке, где их ведут люди. Файл заполняет их, пока поле
# пусто, и не трогает заполненное: иначе правка в карточке молча пропадала
# бы при следующей загрузке BOM, и заметили бы это нескоро.
HEADER_FILL_ONCE = ("gct_pcb", "decimal_pcba")

# Поля, которые на карточке ревизии стоят порознь, а в списке версий
# собираются в одну ячейку «Дополнительные сведения». Порядок здесь и есть
# порядок в ячейке; подписи берутся из самих полей, чтобы не завести им
# второй источник — переименовали поле, и в таблице подпись сменилась сама.
EXTRA_FACT_FIELDS = (
    "developed", "stage", "pcb_supplier", "silkscreen_status",
    "ekb", "assembly", "mpt_registry",
    "gct_bom", "gct_pcb", "previous_revision",
)


class BomHeader:
    """Шапка BOM: поведение ревизии.

    Плата эти поля не хранит — они принадлежат конкретному файлу, и у
    платы их было ровно столько, сколько у последнего импорта. Миксин
    остался у ревизии: правило, чем именно заполнять шапку, должно лежать
    в одном месте, рядом с полями, а не повторяться в представлениях.
    """

    def apply_pn(self, oy_pn):
        """Проставляет номер и разобранные из него ревизии платы и BOM.

        Возвращает базовый номер: плате он нужен — она им опознаётся, —
        а ревизии нет, у неё есть плата.
        """
        self.oy_pn = (oy_pn or "").strip()
        base_pn, self.board_rev, self.bom_rev = parse_pn(self.oy_pn)
        return base_pn

    def apply_header(self, header):
        """Переносит разобранную шапку файла по двум правилам.

        HEADER_FIELDS перезаписываются целиком, HEADER_FILL_ONCE — только
        пока пусты (см. комментарий к спискам). Длина обрезается по самому
        полю: в шапке присланного файла встречается что угодно, и падать на
        слишком длинной строке импорт не должен.
        """
        for name in HEADER_FIELDS:
            setattr(self, name, header.get(name, ""))

        for name in HEADER_FILL_ONCE:
            if getattr(self, name, ""):
                continue
            limit = self._meta.get_field(name).max_length
            setattr(self, name, (header.get(name) or "")[:limit])

    def remember_source(self, username, when=None):
        """Кто и когда загрузил BOM.

        Проставляется при каждой загрузке, а не только при первой: важно,
        когда состав обновляли в последний раз, а не когда ревизия
        появилась. Поэтому imported_at обычное поле, а не auto_now_add.
        """
        self.imported_by = username
        self.imported_at = when or timezone.now()


class BoardQuerySet(models.QuerySet):
    """Списку плат нужно число ревизий — считаем его одним запросом."""

    def with_counts(self):
        """Число ревизий на каждую плату.

        Строк и позиций состава список больше не показывает, поэтому их и
        не считаем: это были два подзапроса на каждую строку страницы, а
        строк на ней пятьдесят. Там, где счётчики всё-таки нужны — карточка,
        подтверждение удаления, — их берут свойства, по запросу на объект.
        """
        counted = self.annotate(revisions_total=Count("revisions", distinct=True))

        # Считающий annotate добавляет GROUP BY, а при нём Django перестаёт
        # считать набор упорядоченным: Meta.ordering в группировку не
        # переносится. Для Paginator это повод предупредить о «непредсказуемом
        # порядке страниц» — и он прав, без ORDER BY база вольна отдать
        # страницы в любом порядке, вплоть до повторов одной платы на разных.
        # Поэтому сортировку задаём явно, сохраняя ту, что просил вызывающий.
        return counted if counted.ordered else counted.order_by(
            *self.model._meta.ordering)


# Тип платы. Список закрытый: по нему фильтруют реестр, а свободный ввод
# развалил бы фильтр на «бэкплейн», «Бэкплейн» и «backplane»
BOARD_TYPES = (
    ("motherboard", "Материнская плата"),
    ("backplane", "Бэкплейн"),
    ("riser", "Райзер"),
    ("interposer", "Интерпозер"),
    ("adapter", "Адаптер"),
    ("control", "Плата управления"),
    ("indicator", "Плата индикации"),
    ("power", "Плата питания"),
    ("other", "Прочее"),
)

class Board(models.Model):
    """Плата: карточка модели и шапка её BOM-файла.

    Здесь лежит то, что не меняется от ревизии к ревизии: назначение,
    тип, разработчик. Всё, что своё у каждой ревизии — ревизии, номера
    PCB и PCBA, поставщик, стадия, — живёт в :class:`BoardRevision`.
    """

    objects = BoardQuerySet.as_manager()

    # базовый номер без суффикса ревизии — он и опознаёт плату:
    # HSBP-5S01-02C и HSBP-5S01-02D это ревизии одной платы
    base_pn = models.CharField(max_length=128, unique=True, null=True,
                               verbose_name="Номер платы")
    imported_at = models.DateTimeField(auto_now=True, verbose_name="Импортировано")
    imported_by = models.CharField(max_length=150, blank=True, default="",
                                   verbose_name="Кто импортировал")

    # Какой ревизия считается текущим. Шапка BOM, номера и даты у платы не
    # хранятся: всё это принадлежит ревизии и живёт в нём — иначе те же
    # значения лежат в двух местах и однажды разойдутся
    current_revision = models.ForeignKey(
        "boards.BoardRevision", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
        verbose_name="Текущая ревизия")

    name = models.CharField(max_length=255, blank=True, default="",
                            verbose_name="Наименование")
    board_type = models.CharField(max_length=16, choices=BOARD_TYPES,
                                  blank=True, default="", db_index=True,
                                  verbose_name="Тип платы")
    purpose = models.TextField(blank=True, default="",
                               verbose_name="Назначение")
    applicability = models.TextField(blank=True, default="",
                                     verbose_name="Применяемость")
    developer = models.CharField(max_length=255, blank=True, default="",
                                 verbose_name="Компания-разработчик")
    # Краткая характеристика — список: «5 SFF», «PCIe Gen5 (32 Gb/s)»,
    # разъёмы, светодиоды. Держим текстом со строки на пункт: набор
    # характеристик у бэкплейна и у платы управления разный, и колонок под
    # них не напасёшься
    specs = models.TextField(blank=True, default="",
                             verbose_name="Краткая характеристика")
    # Предпросмотр в карточке: как плата выглядит сверху и снизу. В базе
    # хранится путь, сам файл лежит в MEDIA_ROOT и раздаётся nginx
    photo_top = models.ImageField(upload_to=images.upload_top, blank=True,
                                  verbose_name="Изображение — Top side")
    photo_bottom = models.ImageField(upload_to=images.upload_bottom, blank=True,
                                     verbose_name="Изображение — Bottom side")

    class Meta:
        ordering = ("base_pn",)
        verbose_name = "Плата"
        verbose_name_plural = "Платы"

    def __str__(self):
        return self.base_pn or f"#{self.pk}"

    def get_absolute_url(self):
        return reverse("boards:detail", args=[self.pk])

    def apply_pn(self, oy_pn):
        """Базовый номер платы из любого номера её ревизии.

        Ревизии и локализация здесь не сохраняются: они свои у каждого
        ревизии, а плата — одна на все.
        """
        self.base_pn, _, _ = parse_pn(oy_pn)
        return self.base_pn

    @property
    def spec_lines(self):
        """Краткая характеристика разобранными пунктами.

        Хранится она текстом — по пункту на строку, вложенность отступом.
        Показывать её как есть нельзя: получается столбик строк, в котором
        не видно, где перечень разъёмов, а где отдельная характеристика.
        Поэтому отдаём пункты с уровнем вложенности и признаком заголовка
        («Разъемы:»), а рисует их шаблон.
        """
        lines = []
        for line in (self.specs or "").splitlines():
            text = line.strip()
            if not text:
                continue
            indent = len(line) - len(line.lstrip())
            lines.append({"text": text,
                          "depth": min(indent // 4, 2),
                          "is_group": text.endswith(":")})
        return lines

    def set_current(self, revision):
        """Делает ревизия текущим: его состав и шапку показывает плата."""
        self.current_revision = revision
        self.save(update_fields=["current_revision"])

    # Счётчики состава берутся у текущей ревизии: состав принадлежит ей.
    # В списке плат они не показываются, поэтому и не считаются пачкой —
    # см. BoardQuerySet.with_counts.

    @property
    def position_count(self):
        return self.current_revision.position_count if self.current_revision else 0

    @property
    def item_count(self):
        return self.current_revision.item_count if self.current_revision else 0

    @property
    def revision_count(self):
        if (value := getattr(self, "revisions_total", None)) is not None:
            return value
        return self.revisions.count()


class BoardRevision(BomHeader, models.Model):
    """Ревизия платы: своя карточка и свой состав.

    Ревизии не перезаписываются — каждый импорт добавляет новую, а прежние
    остаются как история. Так видно, чем ревизия отличается от предыдущего.

    Карточка ревизии отвечает на вопросы, ответы на которые от ревизии к
    ревизии разные: по какой ревизии PCB он собран, что написано на
    шелкографии, чьё производство, на какой стадии. Общее для всех ревизий
    (назначение платы, тип, разработчик) лежит на :class:`Board`.
    """

    board = models.ForeignKey(Board, on_delete=models.CASCADE,
                              related_name="revisions", verbose_name="Плата")
    # внутренний порядковый номер: по нему строятся ссылки
    number = models.PositiveIntegerField(verbose_name="№")
    # номер целиком и разобранные из него ревизии платы и BOM
    oy_pn = models.CharField(max_length=128, blank=True, default="",
                             verbose_name="OY P/N")
    board_rev = models.CharField(max_length=16, blank=True, default="",
                                 verbose_name="Rev")
    bom_rev = models.CharField(max_length=8, blank=True, default="",
                               verbose_name="Rev BOM")

    # Соответствия номеров GCT: у печатной платы своё, у BOM своё, и
    # совпадают они не всегда — поэтому два поля, а не одно.
    gct_pcb = models.CharField(max_length=128, blank=True, default="",
                               verbose_name="Соответствие PCB GCT")
    gct_bom = models.CharField(max_length=128, blank=True, default="",
                               verbose_name="Соответствие BOM GCT")
    # Номер ревизии, от которой эта произошла. В шапке BOM подписан «Old OY
    # BOM P/N», но означает именно предыдущую ревизию, а не «устаревший
    # номер той же» — отсюда и название поля
    previous_revision = models.CharField(
        max_length=128, blank=True, default="",
        verbose_name="Предыдущая ревизия")

    # Сведения о ходе работ по ревизии. Все строковые: значения приходят из
    # карточек и таблиц, где пишут свободно — «в разработке», «согласовано с
    # 12.09», «ООО «Резонит»». Сузить тип до списка или даты можно будет,
    # когда станет видно, что в них попадает на самом деле; пока строка
    # сохраняет всё, а типизация вслепую теряла бы.
    developed = models.CharField(max_length=255, blank=True, default="",
                                 verbose_name="Разработано")
    stage = models.CharField(max_length=255, blank=True, default="",
                             verbose_name="Стадия разработки")
    pcb_supplier = models.CharField(max_length=255, blank=True, default="",
                                    verbose_name="Поставщик PCB")
    # Не путать с silkscreen выше: там обозначение, напечатанное на плате,
    # здесь — состояние работ по шелкографии
    silkscreen_status = models.CharField(max_length=255, blank=True,
                                         default="",
                                         verbose_name="Шелкография")
    ekb = models.CharField(max_length=255, blank=True, default="",
                           verbose_name="ЭКБ")
    # Не путать с assembly_url: там папка на диске R, здесь — состояние сборки
    assembly = models.CharField(max_length=255, blank=True, default="",
                                verbose_name="Сборка")
    mpt_registry = models.CharField(max_length=255, blank=True, default="",
                                    verbose_name="Реестр МПТ")

    # Исполнение. Разбирается из номера (HSBP-4L01-R-02D) и в базовый
    # номер не входит: это та же ревизия платы, собранный в другом месте,
    # а не другая плата
    variant = models.CharField(max_length=4, blank=True, default="",
                               db_index=True, verbose_name="Исполнение")

    # --- карточка ревизии ---
    pcb_name = models.CharField(max_length=128, blank=True, default="",
                                verbose_name="Наименование PCB")
    bom_name = models.CharField(max_length=128, blank=True, default="",
                                verbose_name="Наименование BOM")
    silkscreen = models.CharField(max_length=128, blank=True, default="",
                                  verbose_name="Обозначение на шелкографии")
    panel_count = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Плат в мультизаготовке")
    decimal_pcba = models.CharField(max_length=128, blank=True, default="",
                                    verbose_name="Децимальный номер PCBA")
    decimal_pcb = models.CharField(max_length=128, blank=True, default="",
                                   verbose_name="Децимальный номер PCB")
    pcb_type = models.CharField(max_length=128, blank=True, default="",
                                verbose_name="Вид платы (ПП РФ №719)")
    fru_megarac = models.CharField(max_length=255, blank=True, default="",
                                   verbose_name="FRU-шаблон (MegaRAC)")
    fru_oybmc = models.CharField(max_length=255, blank=True, default="",
                                 verbose_name="FRU-шаблон (OYBMC)")
    spec_1c = models.CharField(max_length=255, blank=True, default="",
                               verbose_name="Ресурсная спецификация (1С)")
    spec_1c_url = models.CharField(max_length=500, blank=True, default="",
                                   verbose_name="Ссылка на спецификацию (1С)")
    # Баллы по ПП РФ №719: от них зависит, попадает ли изделие в реестр
    # отечественной продукции. Число, а не текст: их складывают и сравнивают
    points = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Количество баллов")

    # Раздел «Прикреплённые документы / ссылки» шаблона. Это именно ссылки,
    # а не файлы: документы лежат на диске R и в Confluence, и держать их
    # вторую копию у себя значит однажды показать устаревшую
    source_dir_url = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Папка Source (диск R)")
    manufacture_url = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Папка Manufacture (диск R)")
    assembly_url = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Папка Assembly (диск R)")
    testing_dir_url = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Папка Testing (диск R)")
    eskd_dir_url = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Папка ЕСКД (диск R)")
    test_matrix_url = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Матрица тестового покрытия")
    reference_bom_url = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Эталонный BOM-файл")
    # Снимки ревизии. Рядом с ними долго жили ещё два поля со ссылками из
    # карточек Confluence — они вели кто куда и картинку показать не могли,
    # поэтому после появления загрузки были убраны (0014).
    photo_top = models.ImageField(upload_to=images.revision_top, blank=True,
                                  verbose_name="Изображение — Top side")
    photo_bottom = models.ImageField(upload_to=images.revision_bottom,
                                     blank=True,
                                     verbose_name="Изображение — Bottom side")

    # Ответы чек-листов: {группа: {название документа: {status, comment, url}}}.
    # Раньше это были записи ChecklistItem, по два с лишним десятка на
    # ревизию. Отдельными записями они были нужны, пока несли ещё и описание
    # документа — название, зону ответственности, формат. Описание уехало в
    # шаблон (boards/checklists.py), потому что у всех ревизий оно одно и то
    # же; осталась готовность, и ради неё запись не окупалась: показ карточки
    # стоил отдельного запроса, заведение ревизии — двадцати двух вставок.
    #
    # Значения по шаблону здесь не дублируются: в JSON попадает только то,
    # что заполнил человек. У пустого чек-листа поле — пустой словарь.
    checklist = models.JSONField(default=dict, blank=True,
                                 verbose_name="Ответы чек-листов")

    # Шапка карточки в шаблоне: утверждена она или ещё в работе. Признак и
    # дата раздельно — «утверждена» без даты бесполезно, а дата без признака
    # ни о чём не говорит
    approved = models.BooleanField(default=False,
                                   verbose_name="Карточка утверждена")
    approved_at = models.DateField(null=True, blank=True,
                                   verbose_name="Дата утверждения")


    # Кто и когда загрузил BOM. Пусто — состава из файла у ревизии ещё не
    # было: карточку завели руками, а BOM не присылали.
    imported_at = models.DateTimeField(null=True, blank=True,
                                       verbose_name="Дата загрузки BOM")
    imported_by = models.CharField(max_length=150, blank=True, default="",
                                   verbose_name="Кто загрузил BOM")

    class Meta:
        ordering = ("board", "-number")
        unique_together = ("board", "number")
        verbose_name = "Ревизия платы"
        verbose_name_plural = "Ревизии плат"

    def __str__(self):
        return self.oy_pn or f"{self.board.base_pn} №{self.number}"

    def get_absolute_url(self):
        return reverse("boards:revision", args=[self.board_id, self.number])

    def apply_pn(self, oy_pn):
        """То же, что у платы, плюс исполнение — оно своё у ревизии."""
        super().apply_pn(oy_pn)
        self.variant = variant_of(self.oy_pn)

    @property
    def label(self):
        """Как ревизия называется в интерфейсе."""
        variant = f" · {self.variant}" if self.variant else ""
        if self.board_rev or self.bom_rev:
            return (f"Rev {self.board_rev or '—'} · "
                    f"BOM {self.bom_rev or '—'}{variant}")
        return f"ревизия №{self.number}{variant}"

    @property
    def extra_facts(self):
        """Пары «подпись — значение» для ячейки «Дополнительные сведения».

        Пустые поля пропускаются, и прочерки вместе с ними: десять
        прочерков подряд в ячейке — шум, в котором не видно заполненного.
        А вот слова остаются все: «Реестр МПТ: нет» — это ответ. На самой карточке ревизии прочерки, наоборот, нужны:
        там видно, что поле есть и его не заполнили.
        """
        facts = []
        for name in EXTRA_FACT_FIELDS:
            # Прочерк в карточке пишут вместо пустого, и в сводной ячейке
            # он выглядит как заполненное поле, хотя не значит ничего.
            # is_dash, а не is_placeholder: там заглушкой считается и «нет»,
            # а здесь «Реестр МПТ: нет» — это ответ, а не пропуск.
            value = (getattr(self, name, "") or "").strip()
            if value and not is_dash(value):
                facts.append((self._meta.get_field(name).verbose_name, value))
        return facts

    @property
    def is_current(self):
        return self.board.current_revision_id == self.pk

    @property
    def position_count(self):
        return self.items.filter(kind=BoardItem.MAIN).count()

    @property
    def item_count(self):
        return self.items.count()

    @property
    def unlinked_count(self):
        """Строки, которым не нашлось записи в библиотеке компонентов."""
        return self.items.filter(component_id__isnull=True).count()


class BoardItem(ComponentRefMixin, models.Model):
    """Строка состава. M — основной компонент, S — его замена."""

    MAIN = "M"
    SUBSTITUTE = "S"
    KINDS = ((MAIN, "Основной"), (SUBSTITUTE, "Замена"))

    revision = models.ForeignKey(BoardRevision, on_delete=models.CASCADE,
                                 related_name="items", verbose_name="Ревизия")
    position = models.IntegerField(null=True, blank=True, verbose_name="Позиция")
    kind = models.CharField(max_length=1, choices=KINDS, default=MAIN,
                            verbose_name="Тип строки")

    vendor_pn = models.CharField(max_length=255, blank=True, default="",
                                 verbose_name="Vendor P/N")
    vendor = models.CharField(max_length=255, blank=True, default="",
                              verbose_name="Vendor")
    country = models.CharField(max_length=128, blank=True, default="",
                               verbose_name="Country")
    oy_id = models.CharField(max_length=128, blank=True, default="",
                             verbose_name="OY ID")
    oy_pn = models.CharField(max_length=255, blank=True, default="",
                             verbose_name="OY P/N")
    gbt_pn = models.CharField(max_length=255, blank=True, default="",
                              verbose_name="GBT P/N")
    group = models.CharField(max_length=128, blank=True, default="",
                             verbose_name="Group")
    subgroup = models.CharField(max_length=128, blank=True, default="",
                                verbose_name="Subgroup")
    description = models.TextField(blank=True, default="", verbose_name="Description")
    description_gbt = models.TextField(blank=True, default="",
                                       verbose_name="Description GBT")
    smt_tht = models.CharField(max_length=32, blank=True, default="",
                               verbose_name="SMT/THT")
    references = models.TextField(blank=True, default="",
                                  verbose_name="Part References")
    qty = models.IntegerField(null=True, blank=True, verbose_name="QTY")
    comment = models.TextField(blank=True, default="", verbose_name="Comment")
    row = models.IntegerField(null=True, blank=True, verbose_name="Строка файла")

    # ссылка на запись в библиотеке компонентов: таблица и её ключ.
    # Внешним ключом это сделать нельзя — таблиц компонентов 27, и они
    # неуправляемые. Связь ставится при импорте, поиск применений идёт
    # по ней, а не по строковому сравнению артикулов
    component_table = models.CharField(max_length=64, blank=True, default="",
                                       verbose_name="Таблица компонента")
    component_id = models.IntegerField(null=True, blank=True,
                                       verbose_name="ID компонента")
    component_match = models.CharField(max_length=16, blank=True, default="",
                                       verbose_name="Как сопоставлено")

    class Meta:
        # M идёт раньше S: буквы сортируются в нужном порядке сами
        ordering = ("revision", "position", "kind", "id")
        verbose_name = "Строка состава"
        verbose_name_plural = "Состав платы"
        indexes = [
            models.Index(fields=["vendor_pn"], name="boarditem_vendor_pn_idx"),
            models.Index(fields=["gbt_pn"], name="boarditem_gbt_pn_idx"),
            models.Index(fields=["oy_id"], name="boarditem_oy_id_idx"),
            models.Index(fields=["component_table", "component_id"],
                         name="boarditem_component_idx"),
        ]

    def __str__(self):
        return f"{self.revision_id}: {self.vendor_pn or self.gbt_pn or self.pk}"

    # ---- связь с библиотекой ---------------------------------------------
    # is_linked, component_url и component() приходят из ComponentRefMixin:
    # та же пара «таблица + ключ» стоит и в записях истории, и разбирать её
    # по-разному в двух местах незачем.
    # Состав платы показывается ровно так, как он записан в BOM: значения
    # полей из библиотеки НЕ подставляются. Спецификация — документ, и
    # смотреть на него надо в том виде, в каком его выпустили; если у
    # компонента потом поправили описание, состав прошлой ревизии от этого
    # не изменился. Что в библиотеке сейчас — видно на карточке компонента,
    # ссылка на неё рядом с артикулом.

    @property
    def library_url(self):
        """То же, что ``component_url``: имя оставлено ради шаблонов.

        В bom.html и item_form.html ссылка называется так, и переименовывать
        её ради единообразия — менять работающую разметку без выгоды.
        """
        return self.component_url

    @property
    def is_main(self):
        return self.kind == self.MAIN

    @property
    def reference_list(self):
        """Обозначения списком — разделитель в исходной строке любой."""
        return split_references(self.references)

    def export_value(self, name):
        """Значение поля для выгрузки в BOM-файл.

        I/N проставляется только у основной строки: в исходных BOM замены
        идут под своей позицией без номера, и импорт разбирает их так же —
        берёт номер у последней строки M. Поэтому пустой I/N у замен не
        теряет данные, а делает выгруженный файл похожим на входящий.
        """
        if name == "position" and not self.is_main:
            return None
        if name == "references":
            # разделители приводим к запятым: в исходных файлах встречаются
            # и пробелы, и точки с запятой, а выгрузка должна быть одна
            return normalize_references(self.references)
        return getattr(self, name, None)
