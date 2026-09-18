"""Платы и составы в админке."""

from django.contrib import admin

from .models import Board, BoardItem, BoardRevision


class BoardItemInline(admin.TabularInline):
    model = BoardItem
    fields = ("position", "kind", "vendor_pn", "vendor", "gbt_pn", "qty",
              "component_table", "component_id")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name_plural = "Состав (правится импортом BOM)"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("base_pn", "name", "board_type", "revision_count",
                    "imported_at")
    search_fields = ("base_pn", "name")
    date_hierarchy = "imported_at"
    readonly_fields = ("imported_at", "imported_by")
    save_on_top = True

    @admin.display(description="Ревизий")
    def revision_count(self, obj):
        return obj.revision_count


@admin.register(BoardRevision)
class BoardRevisionAdmin(admin.ModelAdmin):
    """Ревизии создаются импортом BOM, руками их не заводят."""

    list_display = ("board", "oy_pn", "board_rev", "bom_rev",
                    "position_count", "item_count", "unlinked_count",
                    "imported_at")
    list_filter = ("board",)
    search_fields = ("board__base_pn", "oy_pn", "gct_pcb", "gct_bom",
                     "decimal_pcba")
    date_hierarchy = "imported_at"
    inlines = [BoardItemInline]
    readonly_fields = ("board", "number", "oy_pn", "board_rev", "bom_rev",
                       "imported_at", "imported_by")

    @admin.display(description="Позиций")
    def position_count(self, obj):
        return obj.position_count

    @admin.display(description="Строк")
    def item_count(self, obj):
        return obj.item_count

    @admin.display(description="Без компонента")
    def unlinked_count(self, obj):
        return obj.unlinked_count

    def has_add_permission(self, request):
        return False

@admin.register(BoardItem)
class BoardItemAdmin(admin.ModelAdmin):
    list_display = ("revision", "position", "kind", "vendor_pn", "vendor",
                    "gbt_pn", "qty", "component_table", "component_id")
    list_filter = ("kind", "component_match", "revision__board")
    search_fields = ("vendor_pn", "vendor", "gbt_pn", "oy_id", "oy_pn",
                     "description", "references")
    list_select_related = ("revision", "revision__board")
    list_per_page = 50


# Чек-листы в админке отдельной моделью больше не показываются: строки
# перестали быть записями и лежат полем ревизии. Разбирать расхождения
# теперь удобнее на самой странице чек-листов — там видно шаблон целиком,
# а не только заполненные строки.
