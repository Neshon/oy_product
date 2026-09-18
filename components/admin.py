"""Стандартная админка Django для всех таблиц библиотеки."""

from django import forms
from django.contrib import admin, messages

from boards.usage import usage_summary

from .history import ADMIN, record, record_deletion, snapshot
from .mixins import SEARCH_FIELDS, field_names
from .models import ComponentChange, OptionField, OptionValue
from .options import table_choices
from .registry import CATEGORIES

# Заголовки и раздел «Конструктор выпадающих списков» задаёт
# components.admin_site.ComponentsAdminSite — он подключён через AppConfig.

MAX_BOARDS_IN_WARNING = 10
LIST_FILTERS = ("group", "subgroup", "vendor", "status")


class ComponentAdmin(admin.ModelAdmin):
    list_per_page = 50
    save_on_top = True
    show_full_result_count = False
    date_hierarchy = "created"

    def delete_view(self, request, object_id, extra_context=None):
        """Предупреждает, если компонент стоит на платах.

        Django показывает только каскад по своим связям, а связь строк BOM
        внешним ключом не является — про неё он не знает.
        """
        obj = self.get_object(request, object_id)
        if obj is not None:
            self._warn_about_boards(request, obj)
        return super().delete_view(request, object_id, extra_context)

    def _warn_about_boards(self, request, obj):
        boards, rows = usage_summary(obj, self.model._meta.db_table)
        if not boards:
            return
        names = ", ".join(entry["board"].oy_pn
                          for entry in boards[:MAX_BOARDS_IN_WARNING])
        messages.warning(
            request,
            f"Компонент стоит в составах плат ({rows} строк): {names}"
            + (" и другие." if len(boards) > MAX_BOARDS_IN_WARNING else ".")
            + " Строки останутся, но потеряют связь с библиотекой.")

    def get_readonly_fields(self, request, obj=None):
        # id заполняет база, но видеть его при правке полезно
        return ("id",) if obj and "id" in field_names(type(obj)) else ()

    def save_model(self, request, obj, form, change):
        """Пишет правку в ту же историю, что и форма на сайте.

        Через админку правят не реже, чем через сайт, и без этого история в
        карточке была бы с дырами — а история с дырами хуже её отсутствия:
        по ней делают вывод, что запись не трогали.

        Снимок «до» берётся из базы, а не из формы: в админке часть полей
        может быть скрыта или недоступна для правки, и в форме их просто
        нет.
        """
        before = {}
        if change and obj.pk is not None:
            current = self.model.objects.filter(pk=obj.pk).first()
            if current is not None:
                before = snapshot(current)

        super().save_model(request, obj, form, change)
        record(obj, self.model._meta.db_table, request.user, before,
               source=ADMIN)

    def delete_model(self, request, obj):
        """Удаление через админку тоже попадает в историю.

        Запись делается до удаления: после него не останется ни значений,
        ни ключа. Увидеть её можно в разделе «История изменений» — карточки
        у удалённого компонента больше нет.
        """
        record_deletion(obj, self.model._meta.db_table, request.user,
                        source=ADMIN)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """То же для массового удаления из списка.

        Django не зовёт delete_model для каждой записи — иначе групповое
        удаление проходило бы мимо истории целиком, а это как раз тот
        случай, когда позже спрашивают, куда делись полсотни строк.
        """
        table = self.model._meta.db_table
        for obj in queryset:
            record_deletion(obj, table, request.user, source=ADMIN)
        super().delete_queryset(request, queryset)


class ReadOnlyComponentAdmin(ComponentAdmin):
    """Для таблиц, помеченных в реестре read_only: смотреть можно, менять — нет."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _admin_options(category):
    """Настройки ModelAdmin, выведенные из реестра и полей модели."""
    names = category.field_names
    has_id = "id" in names
    columns = (["id"] if has_id else []) + list(category.columns)

    options = {
        "list_display": tuple(columns) or ("__str__",),
        "list_filter": tuple(f for f in LIST_FILTERS if f in names),
        "search_fields": tuple(f for f in SEARCH_FIELDS if f in names),
    }
    if has_id:
        options["list_display_links"] = ("id",)
        options["ordering"] = ("-id",)
    elif category.columns:
        options["list_display_links"] = (category.columns[0],)
    if "created" not in names:
        options["date_hierarchy"] = None
    return options


def _register(category):
    base = ReadOnlyComponentAdmin if category.read_only else ComponentAdmin
    admin_class = type(f"{category.model.__name__}Admin", (base,),
                       _admin_options(category))
    admin.site.register(category.model, admin_class)


for _category in CATEGORIES.values():
    _register(_category)


# ---- конструктор выпадающих списков --------------------------------------
class OptionFieldForm(forms.ModelForm):
    """Таблицы выбираются галочками — список берётся из реестра групп."""

    tables = forms.MultipleChoiceField(
        required=False,
        label="Таблицы",
        help_text="Ничего не отмечено — список работает во всех таблицах",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = OptionField
        fields = ("field", "label", "tables", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tables"].choices = table_choices()
        if self.instance.pk:
            self.initial["tables"] = self.instance.tables or []

    def clean_tables(self):
        return list(self.cleaned_data["tables"])


class OptionValueInline(admin.TabularInline):
    """Значения столбца добавляются и правятся прямо на его странице."""

    model = OptionValue
    fields = ("value", "is_active")
    # без заготовок: новая строка добавляется ссылкой под таблицей
    extra = 0
    verbose_name = "значение"
    verbose_name_plural = "Значения выпадающего списка"


@admin.register(OptionField)
class OptionFieldAdmin(admin.ModelAdmin):
    form = OptionFieldForm
    inlines = [OptionValueInline]
    list_display = ("__str__", "field", "value_count", "table_list", "is_active")
    list_filter = ("is_active",)
    search_fields = ("field", "label", "values__value")
    save_on_top = True

    fieldsets = (
        (None, {
            "fields": ("field", "label", "is_active"),
            "description": "Столбец — имя поля модели, например smt_tht. "
                           "Пока он активен, поле показывается выпадающим "
                           "списком в формах и в фильтрах над таблицей. "
                           "Один столбец можно завести несколько раз — "
                           "с разными наборами таблиц.",
        }),
        ("Где работает", {"fields": ("tables",)}),
    )

    @admin.display(description="Значений")
    def value_count(self, obj):
        return obj.values.count()

    @admin.display(description="Таблицы")
    def table_list(self, obj):
        return ", ".join(obj.tables) if obj.tables else "все"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("values")


@admin.register(ComponentChange)
class ComponentChangeAdmin(admin.ModelAdmin):
    """История правок — только для чтения.

    Править историю через админку нельзя: запись, которую можно
    отредактировать, перестаёт быть свидетельством. Удалять — можно, иначе
    от старых записей не избавиться, когда их станет слишком много.
    """

    list_display = ("created", "author", "action", "component_table",
                    "component_id", "fields_count", "source")
    list_filter = ("action", "source", "component_table")
    search_fields = ("author", "component_table")
    date_hierarchy = "created"
    ordering = ("-created",)

    @admin.display(description="Полей")
    def fields_count(self, obj):
        return obj.fields_count

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
