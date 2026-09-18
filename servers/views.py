"""Страницы раздела серверов: список, карточка, состав, отчёты, импорт."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from components.export import csv_response
from components.permissions import board_editor

from . import tree
from .forms import BomLineForm, ItemForm, SystemBomUploadForm
from .importer import ImportError_, apply_rows, read
from .models import BomLine, Item

PAGE_SIZE = 50


def _page(request, queryset):
    paginator = Paginator(queryset, PAGE_SIZE)
    return paginator.get_page(request.GET.get("page"))


def item_list(request):
    term = (request.GET.get("q") or "").strip()
    kind = (request.GET.get("kind") or "").strip()

    items = Item.objects.with_counts().search(term)
    if kind:
        items = items.filter(kind=kind)

    return render(request, "servers/list.html", {
        "page": _page(request, items),
        "term": term,
        "kind": kind,
        "kinds": Item.KINDS,
    })


def item_detail(request, pk):
    item = get_object_or_404(Item.objects.select_related("board"), pk=pk)
    try:
        used_in = tree.where_used(item.pk)
    except DatabaseError as exc:
        used_in = []
        messages.error(request, f"Не удалось посчитать применяемость: {exc}")

    return render(request, "servers/detail.html", {
        "item": item,
        "lines": item.own_lines(),
        "used_in": used_in,
        "details": sorted((item.details or {}).items()),
    })


def item_tree(request, pk):
    """Полное разузлование: состав до последнего компонента."""
    item = get_object_or_404(Item, pk=pk)
    rows = tree.explode(item.pk)

    if request.GET.get("export") == "csv":
        return csv_response(
            f"{item.oy_pn}-tree.csv",
            ["Уровень", "OY P/N", "GCT P/N", "Описание", "Количество", "Ед."],
            ([row["depth"], row["oy_pn"], row["gct_pn"], row["description"],
              row["quantity"], row["unit"]] for row in rows))

    return render(request, "servers/tree.html", {"item": item, "rows": rows})


def item_where_used(request, pk):
    item = get_object_or_404(Item, pk=pk)
    return render(request, "servers/where_used.html", {
        "item": item, "rows": tree.where_used(item.pk)})


def item_summary(request, pk):
    """Сводка: сколько всего каждой покупной позиции в изделии."""
    item = get_object_or_404(Item, pk=pk)
    rows = tree.summary(item.pk)

    if request.GET.get("export") == "csv":
        return csv_response(
            f"{item.oy_pn}-summary.csv",
            ["OY P/N", "GCT P/N", "Описание", "Количество", "Ед."],
            ([row["oy_pn"], row["gct_pn"], row["description"],
              row["quantity"], row["unit"]] for row in rows))

    return render(request, "servers/summary.html", {"item": item, "rows": rows})


# ---- правка ---------------------------------------------------------------

@board_editor
def item_edit(request, pk=None):
    item = get_object_or_404(Item, pk=pk) if pk else None
    form = ItemForm(request.POST or None, instance=item)

    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Позиция «{saved.oy_pn}» сохранена.")
        return redirect(saved.get_absolute_url())

    return render(request, "servers/form.html", {"form": form, "item": item})


@board_editor
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    used_in = tree.where_used(item.pk)

    if request.method == "POST":
        # Проверяем по самим строкам, а не по применяемости: разузлование
        # идёт только по основным строкам, и позиция, стоящая где-то
        # заменой, в него не попадёт — а PROTECT в модели сработает и
        # уронит запрос ошибкой базы
        if item.used_in.exists():
            messages.error(
                request,
                "Позиция входит в состав других изделий — сначала уберите её "
                "оттуда.")
            return redirect(item.get_absolute_url())
        number = item.oy_pn
        item.delete()
        messages.success(request, f"Позиция «{number}» удалена.")
        return redirect("servers:list")

    return render(request, "servers/confirm_delete.html",
                  {"item": item, "used_in": used_in})


@board_editor
def line_edit(request, pk, line_pk=None):
    parent = get_object_or_404(Item, pk=pk)
    if parent.is_board:
        messages.warning(
            request,
            "Состав платы ведётся в разделе плат — через импорт BOM или "
            "правку её ревизии.")
        return redirect(parent.get_absolute_url())

    line = get_object_or_404(BomLine, pk=line_pk, parent=parent) if line_pk else None
    form = BomLineForm(request.POST or None, instance=line, parent=parent)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Строка состава сохранена.")
        return redirect(parent.get_absolute_url())

    return render(request, "servers/line_form.html",
                  {"form": form, "item": parent, "line": line})


@board_editor
def line_delete(request, pk, line_pk):
    parent = get_object_or_404(Item, pk=pk)
    line = get_object_or_404(BomLine, pk=line_pk, parent=parent)
    if request.method == "POST":
        line.delete()
        messages.success(request, "Строка состава удалена.")
    return redirect(parent.get_absolute_url())


# ---- импорт ---------------------------------------------------------------

@board_editor
def bom_import(request):
    """Загрузка System BOM: состав изделия одним файлом."""
    form = SystemBomUploadForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            header, rows = read(upload)
        except ImportError_ as exc:
            messages.error(request, f"{upload.name}: {exc}")
            return render(request, "servers/import.html", {"form": form})

        with transaction.atomic():
            report = apply_rows(header, rows, source=upload.name,
                                replace=form.cleaned_data["replace"])

        messages.success(
            request,
            f"«{report['parent'].oy_pn}»: строк состава {report['lines']}, "
            f"заведено новых позиций {len(report['items_created'])}.")
        if report["assumed"]:
            messages.warning(
                request,
                "Без пометки M/S, приняты за основные строки: "
                + ", ".join(str(row) for row in report["assumed"]))
        if report["skipped"]:
            messages.warning(
                request,
                "Пропущены строки: "
                + ", ".join(f"{row} — {why}" for row, why in report["skipped"]))
        return redirect(report["parent"].get_absolute_url())

    return render(request, "servers/import.html", {"form": form})
