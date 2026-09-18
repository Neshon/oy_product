"""Формы раздела плат: загрузка BOM и ручное ведение состава."""

import hashlib

from django import forms

from components.matching import is_placeholder

from . import checklists, images
from .models import Board, BoardItem, BoardRevision
from .pn import match_key
from .references import normalize_references
from .revisions import parse_pn


class MultipleFileInput(forms.ClearableFileInput):
    """Штатный виджет не разрешает выбирать несколько файлов."""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Поле, возвращающее список файлов вместо одного."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(
            attrs={"accept": ".xlsx,.xlsm", "multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        clean_one = super().clean
        if isinstance(data, (list, tuple)):
            return [clean_one(item, initial) for item in data]
        return [clean_one(data, initial)]


class BomUploadForm(forms.Form):
    file = MultipleFileField(
        label="BOM-файлы",
        help_text="Excel-файлы с листом «BOM». Можно выбрать сразу несколько — "
                  "каждый разбирается отдельно, ошибка в одном не отменяет остальные")

    def clean_file(self):
        files = self.cleaned_data["file"]
        wrong = [f.name for f in files
                 if not f.name.lower().endswith((".xlsx", ".xlsm"))]
        if wrong:
            raise forms.ValidationError(
                "Нужен Excel в формате .xlsx или .xlsm. Не подходят: "
                + ", ".join(wrong))
        return files


class PhotoFieldsMixin:
    """Проверка и уменьшение загруженных снимков.

    Одинаково нужна карточке платы и карточке ревизии, поэтому лежит
    отдельно: логика «проверить формат, повернуть по EXIF, уменьшить» —
    одна на оба случая, и расходиться ей незачем.

    Форма перечисляет свои файловые поля в ``photo_fields``; для каждого
    ставится подсказка, фильтр по типу в диалоге выбора файла и очистка.
    """

    photo_fields = ()

    def setup_photos(self):
        """Вызывается из __init__ после super()."""
        for name in self.photo_fields:
            field = self.fields[name]
            field.widget.attrs["accept"] = "image/jpeg,image/png,image/webp"
            field.help_text = (
                "JPEG, PNG или WebP до 12 МБ. Большие уменьшаются до 1600 px "
                "по длинной стороне — карточке хватает, а грузится быстрее")

    def clean_picture(self, name):
        """Проверяет и уменьшает одно изображение."""
        picture = self.cleaned_data.get(name)
        # поле не трогали или очистили — проверять нечего
        if not picture or not hasattr(picture, "file") \
                or not hasattr(picture, "content_type"):
            return picture

        images.check(picture)
        smaller = images.shrink(picture)
        picture.file = smaller.file
        picture.size = smaller.size
        return picture

    def clean_photo_top(self):
        return self.clean_picture("photo_top")

    def clean_photo_bottom(self):
        return self.clean_picture("photo_bottom")


class BoardForm(PhotoFieldsMixin, forms.ModelForm):
    """Заведение платы руками, без файла BOM."""

    class Meta:
        model = Board
        fields = ("base_pn", "name", "board_type", "developer",
                  "purpose", "applicability", "specs",
                  "photo_top", "photo_bottom")

    photo_fields = ("photo_top", "photo_bottom")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # класс "field" виджетам больше не проставляем: его ставит crispy по
        # типу виджета (CRISPY_CLASS_CONVERTERS в settings)
        self.setup_photos()
        self.fields["base_pn"].required = True
        self.fields["base_pn"].help_text = (
            "Номер платы без ревизии, например HSBP-5S01. Можно ввести и "
            "полный номер с ревизией — она и локализация отбросятся")
        for name in ("purpose", "applicability", "specs"):
            self.fields[name].widget = forms.Textarea(attrs={"rows": 5})

    def clean_base_pn(self):
        """Номер приводится к базовому: платой считается модель, не ревизия."""
        value = (self.cleaned_data["base_pn"] or "").strip()
        if is_placeholder(value):
            raise forms.ValidationError(
                "Укажите номер платы: по нему её опознают в системе")

        base_pn, _, _ = parse_pn(value)
        existing = Board.objects.filter(base_pn__iexact=base_pn)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError(
                f"Плата {base_pn} уже заведена. "
                f"Новая ревизия добавляется импортом BOM.")
        return base_pn


class BoardRevisionForm(PhotoFieldsMixin, forms.ModelForm):
    """Карточка ревизии.

    Номер ревизии здесь не правится: он приходит из BOM-файла, и из него же
    разбираются ревизии и исполнение. Менять его руками значило бы
    развести номер и разобранные из него поля.
    """

    class Meta:
        model = BoardRevision
        # порядок — как строки карточки в шаблоне Confluence: правя одно и
        # то же в двух местах, человек не должен искать поле заново
        fields = ("pcb_name", "bom_name", "silkscreen", "panel_count",
                  "fru_megarac", "fru_oybmc", "decimal_pcba", "decimal_pcb",
                  "spec_1c", "spec_1c_url", "pcb_type", "points",
                  # gct_pcb приходит и из шапки BOM, но правится и здесь:
                  # загрузка заполняет его, только пока он пуст
                  # (BomHeader.HEADER_FILL_ONCE), так что правка не пропадёт
                  "gct_pcb", "gct_bom",
                  # ход работ: ни импорт BOM, ни карточки Confluence их не
                  # заполняют, значит правятся только здесь
                  "developed", "stage", "pcb_supplier", "silkscreen_status",
                  "ekb", "assembly", "mpt_registry",
                  "photo_top", "photo_bottom",
                  "source_dir_url", "manufacture_url", "assembly_url",
                  "testing_dir_url", "eskd_dir_url", "test_matrix_url",
                  "reference_bom_url", "approved", "approved_at")

    photo_fields = ("photo_top", "photo_bottom")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_photos()
        self.fields["approved"].widget = forms.CheckboxInput(
            attrs={"class": "checkbox"})
        self.fields["approved_at"].widget = forms.DateInput(
            attrs={"type": "date"}, format="%Y-%m-%d")


class BoardRevisionCreateForm(BoardRevisionForm):
    """Заведение ревизии руками, без файла BOM.

    От правки отличается одним полем — номером ревизии. При правке его нет
    намеренно: номер приходит из файла, и из него же разбираются ревизии и
    локализация. Здесь файла нет, поэтому номер спрашиваем — но разбираем
    так же, чтобы ревизия, заведённая руками, ничем не отличалась от
    загруженной.
    """

    oy_pn = forms.CharField(
        label="Номер ревизии", max_length=128,
        help_text="Например HSBP-5S01-02C: из него разберутся ревизия платы "
                  "(0.2), ревизия BOM (C) и локализация",
        widget=forms.TextInput())

    # номер идёт первым: остальное — карточка, а это опознавательный знак
    field_order = ("oy_pn",)

    def __init__(self, *args, board=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.board = board

    def clean_oy_pn(self):
        value = (self.cleaned_data["oy_pn"] or "").strip()
        if is_placeholder(value):
            raise forms.ValidationError("Укажите номер ревизии")

        base_pn, board_rev, bom_rev = parse_pn(value)
        if not board_rev and not bom_rev:
            raise forms.ValidationError(
                "В номере не видно ревизии — проверьте запись, например "
                "HSBP-5S01-02C")

        if self.board is not None:
            if match_key(base_pn) != match_key(self.board.base_pn):
                raise forms.ValidationError(
                    f"Это ревизия платы {base_pn}, а не {self.board.base_pn}")

            twin = [item for item in self.board.revisions.all()
                    if match_key(item.oy_pn) == match_key(value)]
            if twin:
                raise forms.ValidationError("Такая ревизия у платы уже есть")
        return value


class ChecklistForm(forms.Form):
    """Все чек-листы ревизии одной формой.

    Не ModelForm и не formset: строки больше не записи. Поля собираются по
    шаблону и сохранённым ответам (:mod:`boards.checklists`), а сохраняются
    одним полем ревизии.

    Имя поля — не название документа: в них пробелы, кириллица и скобки, и
    в имени HTML-поля им делать нечего. Вместо этого короткий отпечаток от
    пары «группа + название»: он одинаков при показе и при отправке, не
    зависит от порядка строк и переживает добавление новых.
    """

    def __init__(self, *args, revision=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.revision = revision
        self.groups = checklists.groups_for(revision)
        self.by_key = {}

        for group in self.groups:
            for row in group.rows:
                key = self.key_of(row.group, row.title)
                self.by_key[key] = row
                row.form_key = key

                # Классы проставлены руками: строки чек-листа рисуются в
                # ячейках таблицы напрямую ({{ row.fields.0 }}), а не через
                # as_crispy_field — разметка строки формы там не нужна.
                self.fields[f"status_{key}"] = forms.ChoiceField(
                    choices=checklists.STATUSES, required=False,
                    initial=row.status,
                    widget=forms.Select(attrs={"class": "field"}))
                self.fields[f"comment_{key}"] = forms.CharField(
                    required=False, initial=row.comment,
                    widget=forms.TextInput(attrs={"class": "field"}))
                self.fields[f"url_{key}"] = forms.CharField(
                    required=False, initial=row.url, max_length=500,
                    widget=forms.TextInput(attrs={"class": "field",
                                                  "placeholder": "ссылка"}))

        # Поля кладём на сами строки — вторым проходом, когда все они уже
        # объявлены: BoundField берётся у готовой формы. Так шаблону не надо
        # собирать имена полей из группы и названия, а значит и знать, как
        # они устроены.
        for group in self.groups:
            for row in group.rows:
                row.fields = tuple(self[f"{name}_{row.form_key}"]
                                   for name in ("status", "comment", "url"))

    @staticmethod
    def key_of(group, title):
        digest = hashlib.md5(f"{group}\x1f{title}".encode("utf-8"))
        return digest.hexdigest()[:12]

    def save(self):
        updates = {
            (row.group, row.title): {
                "status": self.cleaned_data.get(f"status_{key}", ""),
                "comment": self.cleaned_data.get(f"comment_{key}", ""),
                "url": self.cleaned_data.get(f"url_{key}", ""),
            }
            for key, row in self.by_key.items()
        }
        return checklists.save_answers(self.revision, updates)


class BoardItemForm(forms.ModelForm):
    """Строка состава: то, что принадлежит плате, а не компоненту.

    Артикулы, производитель и описание здесь не спрашиваются, и это главное
    в этой форме. Взяться им неоткуда, кроме двух источников: BOM-файла,
    который разобрал импорт, и карточки компонента, которую выбрали в
    библиотеке. Ввод третьего значения руками порождал бы строку, которая
    ссылается на один компонент, а называется по-другому, — причём молча,
    потому что расхождение видно только при сверке с библиотекой.

    Остаётся то, чего в библиотеке нет и быть не может: под каким номером
    позиция стоит в спецификации, основная это строка или замена, какие у
    неё обозначения на плате, сколько штук и что к ней приписали.
    """

    class Meta:
        model = BoardItem
        fields = ("position", "kind", "references", "qty", "comment")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Комментарию нужна textarea, а не строка: в него пишут фразами.
        # Класс подставит crispy по типу виджета.
        self.fields["comment"].widget = forms.Textarea(attrs={"rows": 3})
        self.fields["references"].help_text = (
            "Через запятую: C1, C4, C7. Пробелы и точки с запятой тоже подойдут — приведём сами")
        self.fields["position"].help_text = "Пусто — следующий свободный номер"
        self.fields["qty"].help_text = "Сколько таких на плате"

    def clean_references(self):
        # тем же правилом, что и при импорте: в базе один вид записи
        return normalize_references(self.cleaned_data.get("references"))
