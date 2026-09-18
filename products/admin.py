"""Позиции и состав в админке — для разбора сложных случаев.

Обычная работа идёт на сайте: там видно состав деревом и применяемость.
Здесь остаётся то, для чего интерфейс не нужен, — массовая правка и
просмотр строк, у которых нет карточки.
"""

from django.contrib import admin

from .models import BomLine, Item


class BomLineInline(admin.TabularInline):
    model = BomLine
    fk_name = "parent"
    extra = 0
    fields = ("position", "kind", "child", "oy_pn", "gct_pn", "quantity",
              "unit", "designator", "source")
    autocomplete_fields = ("child",)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("oy_pn", "name", "kind", "status", "gct_pn",
                    "decimal_number", "updated")
    list_filter = ("kind", "status")
    search_fields = ("oy_pn", "gct_pn", "name", "decimal_number")
    inlines = (BomLineInline,)


@admin.register(BomLine)
class BomLineAdmin(admin.ModelAdmin):
    list_display = ("parent", "position", "kind", "label", "quantity", "unit",
                    "source")
    list_filter = ("kind", "unit")
    search_fields = ("oy_pn", "gct_pn", "description", "parent__oy_pn")
    autocomplete_fields = ("parent", "child")
