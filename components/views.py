"""Веб-интерфейс библиотеки: список, карточка, создание, правка, удаление.

Помощники списка вынесены в :mod:`components.listing`, импорт внешних
ссылок — в :mod:`components.link_views`.
"""

from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views import View

from boards.search import search_boards, search_items
from boards.stats import bom_coverage
from boards.usage import find_usages, usage_summary

from .cache import COUNTS_KEY, cached
from .db import fallback, unavailable
from .defaults import defaults
from .duplicates import CHECKS, DEFAULT_CHECK, find_duplicates
from .export import csv_response, export_stamp
from .forms import (FilterForm, build_form_class, group_fields,
                    sample_initial)
from .history import (history, log_authors, log_queryset, record,
                      record_deletion, record_duplicate, snapshot,
                      with_authors)
from .listing import (PAGE_SIZES, category_or_404, fetch,
                      filter_choices, page_size, sorted_queryset)
from .lookup import matches
from .matching import usable
from .models import ComponentChange
from .numbering import next_oy_id
from .permissions import admin_only, component_editor
from .querystring import with_params
from .refs import resolve
from .registry import (CATEGORIES, MAIN_CATEGORIES, REPLACEMENT_CATEGORIES,
                       counterpart)

RELATED_LIMIT = 50
SEARCH_PREVIEW = 10
DUPLICATE_PAGE_SIZE = 50


def _read_only_redirect(request, category):
    """Уводит из группы, которую менять нельзя. Иначе возвращает None.

    Проверка нужна и форме, и удалению, а список групп «только для
    чтения» ведёт реестр — значит, и ответ на неё должен быть один.
    """
    if not category.read_only:
        return None
    messages.warning(request, f"«{category.title}» открыт только для чтения.")
    return redirect("components:list", slug=category.slug)


# ---- главная -------------------------------------------------------------

def _count_rows():
    """Сколько записей в каждой рабочей группе. Возвращает (строки, сбои)."""
    rows, failed = [], []
    for category in MAIN_CATEGORIES:
        with unavailable(category.table, failed):
            rows.append({"table": category.table,
                         "count": category.model.objects.count()})
    return rows, failed


def dashboard(request):
    """Стартовая страница: сколько чего лежит в справочнике.

    Четырнадцать ``COUNT(*)`` по большим таблицам — заметная цена для
    страницы, которую открывают чаще всех остальных, поэтому счётчики
    кэшируются. В кэш кладутся только числа: категории в нём хранить нельзя,
    да и незачем — они и так под рукой.
    """
    counted, failed = cached(COUNTS_KEY, _count_rows)

    by_table = {item["table"]: item["count"] for item in counted}
    rows = [{"category": category, "count": by_table[category.table]}
            for category in MAIN_CATEGORIES if category.table in by_table]

    top = max((row["count"] for row in rows), default=0) or 1
    for row in rows:
        row["share"] = round(row["count"] / top * 100)
    rows.sort(key=lambda row: -row["count"])

    return render(request, "components/dashboard.html", {
        # насколько состав плат опирается на библиотеку, а не на текст из файла
        "coverage": bom_coverage(),
        "rows": rows,
        "total": sum(row["count"] for row in rows),
        "failed": failed,
        "replacement_categories": REPLACEMENT_CATEGORIES,
    })


# ---- список --------------------------------------------------------------

def component_list(request, slug):
    category = category_or_404(slug)
    model = category.model

    filters = filter_choices(category, request.GET)
    filter_form = FilterForm(request.GET or None, filters=filters)

    queryset = (model.objects.all()
                .search(request.GET.get("q"))
                .apply_filters(request.GET, category.filter_fields))
    queryset, sort, direction = sorted_queryset(queryset, category, request)

    if request.GET.get("export") == "csv":
        return _export_csv(category, queryset,
                           request.user.get_username())

    per_page = page_size(request)
    paginator = Paginator(queryset, per_page)
    page = paginator.get_page(request.GET.get("page"))

    columns = category.verbose_columns
    rows = [{"obj": obj,
             "cells": [(name, getattr(obj, name)) for name, _ in columns]}
            for obj in page.object_list]

    return render(request, "components/list.html", {
        "category": category,
        "columns": columns,
        "rows": rows,
        "page": page,
        "paginator": paginator,
        "filter_form": filter_form,
        "sort": sort,
        "dir": direction,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "export_url": with_params(request.GET, export="csv"),
    })


def _export_csv(category, queryset, username=""):
    """Выгрузка списка компонентов с отметкой о том, кто её сделал.

    Отметка стоит перед таблицей, как в выгрузке состава платы: файл уходит
    в переписку, и по нему должно быть видно, кто и когда его достал. Из-за
    неё заголовок колонок — третья строка, а не первая; Excel это
    переживает, а читающему CSV программой нужен пропуск двух строк.
    """
    fields = category.ordered_fields
    filename = f"{slugify(category.table) or category.slug}.csv"
    rows = ([getattr(obj, f.name) for f in fields]
            for obj in queryset.iterator(chunk_size=500))
    return csv_response(filename, [str(f.verbose_name) for f in fields], rows,
                        preamble=export_stamp(username))


# ---- карточка ------------------------------------------------------------

def _related_by_oy_id(category, obj, oy_id):
    """Аналоги: записи с тем же OY ID в этой таблице и в парной ей.

    Заглушки вроде «---» и «?» сюда не доходят — по ним в аналоги попало бы
    всё, у чего OY ID тоже не заполнен.
    """
    if not oy_id:
        return []
    sources = [c for c in (category, counterpart(category)) if c is not None]
    # оригиналы идут первыми, замены следом
    sources.sort(key=lambda c: c.replacement)

    related = []
    for source in sources:
        found = source.model.objects.filter(oy_id=oy_id)
        if source.slug == category.slug:
            found = found.exclude(pk=obj.pk)
        related += [{"obj": item, "category": source}
                    for item in found[:RELATED_LIMIT]]
    return related[:RELATED_LIMIT]


def component_detail(request, slug, pk):
    category = category_or_404(slug)
    obj = fetch(category, pk)
    # суррогатный id — служебный, пользователю он ничего не говорит
    fields = [(f.verbose_name, getattr(obj, f.name), f.name)
              for f in category.ordered_fields
              if not (f.primary_key and f.get_internal_type() == "AutoField")]
    filled = [f for f in fields if f[1] not in (None, "")]

    oy_id = usable(getattr(obj, "oy_id", ""))
    # где этот компонент стоит на платах: по связи из импорта,
    # а если её нет — по артикулам
    usages, matched_by = find_usages(obj, category.table)

    return render(request, "components/detail.html", {
        "category": category,
        "object": obj,
        "filled": filled,
        "usages": usages,
        "usage_match": matched_by,
        "changes": history(category.table, obj.pk),
        "pair": counterpart(category),
        "oy_id": oy_id,
        "related": _related_by_oy_id(category, obj, oy_id),
        "related_limit": RELATED_LIMIT,
    })


# ---- создание и правка ---------------------------------------------------

@method_decorator(component_editor, name="dispatch")
class ComponentEditView(View):
    """Создание и правка — одна форма на оба случая."""

    template_name = "components/form.html"

    def dispatch(self, request, slug, pk=None, *args, **kwargs):
        self.category = category_or_404(slug)
        read_only = _read_only_redirect(request, self.category)
        if read_only is not None:
            return read_only

        self.source = None
        if self.category.replacement and pk is None:
            redirect_response = self._require_source(request, slug)
            if redirect_response is not None:
                return redirect_response

        self.object = (self.category.model() if pk is None
                       else fetch(self.category, pk))
        self.created = self.object.pk is None
        # компонент, с которого списываем параметры («Добавить по образцу»)
        self.sample = self._find_sample(request) if self.created else None

        # Снимок «до» берётся здесь, а не в post(), и это принципиально.
        # ModelForm переносит присланные данные на instance ещё во время
        # is_valid() — в _post_clean(). Дальше self.object уже держит новые
        # значения, сравнивать его с самим собой бессмысленно, и история
        # правок оставалась пустой. Здесь запись только что прочитана из
        # базы и формы ещё не касалась.
        self.before = {} if self.created else snapshot(self.object)

        self.locked = self._locked_fields()
        # OY ID в форму не выводится: править его нельзя, а место в первом
        # ряду занимает то, что действительно вводят. Значение показывается
        # в шапке и проставляется при сохранении.
        self.oy_id, self.oy_id_hint = self._lock_oy_id()
        return super().dispatch(request, *args, **kwargs)

    def _find_sample(self, request):
        """Компонент из ?like= — образец для нового.

        Берётся только из этой же группы: у соседней таблицы другой набор
        полей, и перенос превратился бы в угадывание. Пропавший или
        неверный ключ — не ошибка: форма просто откроется пустой.
        """
        pk = request.GET.get("like")
        if not pk:
            return None
        try:
            return self.category.model.objects.filter(pk=pk).first()
        except (DatabaseError, ValueError, TypeError):
            return None

    def _require_source(self, request, slug):
        """Замену заводят только из карточки основного компонента.

        OY ID берётся оттуда: без него аналог не с чем связать. Возвращает
        перенаправление, если основного компонента нет, иначе None.
        """
        origin = counterpart(self.category)
        source_pk = request.POST.get("from") or request.GET.get("from")
        source = None
        if origin and source_pk:
            try:
                source = origin.model.objects.filter(pk=source_pk).first()
            except (DatabaseError, ValueError, TypeError):
                source = None

        if source is None:
            messages.warning(
                request,
                "Замену можно добавить только из карточки основного "
                "компонента — в блоке «аналоги по OY ID».")
            return redirect("components:list",
                            slug=origin.slug if origin else slug)

        if not usable(source.oy_id):
            messages.warning(
                request,
                f"У компонента {source.display_title()} не заполнен OY ID — "
                f"сначала укажите его, иначе замену не с чем связать.")
            return redirect(source.get_absolute_url())

        self.source = source
        return None

    def _locked_fields(self):
        """``{поле: (значение, пояснение)}`` — что показываем, но не даём править.

        Пустой словарь для поля означает «оставить редактируемым»: подобрать
        значение не удалось, и заперев поле, мы бы не дали завести первую
        запись в пустой таблице.
        """
        locked = {}

        group = self._lock_group()
        if group:
            # без пояснения: поле и так заперто и заполнено, а подпись
            # «определяется группой компонентов» повторяла название группы,
            # написанное строкой выше
            locked["group"] = (group, "")

        return locked

    def _lock_oy_id(self):
        """Значение OY ID и пояснение, откуда оно взялось.

        У замены оно приходит от основного компонента, у существующей записи
        остаётся прежним, у нового компонента вычисляется по нумерации.
        Если вычислить нечего (в таблице ещё нет ни одного ID) или в записи
        стоит заглушка — поле остаётся редактируемым, иначе завести первый
        компонент было бы нечем.
        """
        if self.source:
            return self.source.oy_id, (f"Берётся у основного компонента "
                                       f"{self.source.display_title()}")
        if self.object.pk:
            return (usable(getattr(self.object, "oy_id", "")) or None,
                    "Идентификатор записи не меняется")
        return (next_oy_id(self.category) or None,
                "Следующий свободный номер, назначается автоматически")

    def _lock_group(self):
        """Значение Group: оно определяется таблицей, а не автором записи.

        У существующей записи остаётся своё: подменять его на общее по
        группе значило бы молча править данные, за которыми сюда не
        приходили. Незаполненное — случай другой: там заполнять нечего, и
        подставляется общее.
        """
        if "group" not in self.category.field_names:
            return None
        if self.object.pk:
            current = usable(getattr(self.object, "group", ""))
            if current:
                return current
        return defaults(self.category).get("group")

    def _lock_widgets(self, form):
        """Запирает поля; пояснение под полем — если оно там нужно.

        ``disabled`` вместо ``readonly``: readonly в браузере обходится, а
        disabled Django обрабатывает сам — присланные данные для такого поля
        игнорируются, и берётся значение из ``initial``. Поэтому подменить
        его запросом нельзя, и доопределять поле при сохранении не нужно.
        """
        for name, (value, hint) in self.locked.items():
            field = form.fields.get(name)
            if field is None:
                continue
            field.disabled = True
            # пустое пояснение убирает подпись под полем, в том числе ту,
            # что могла остаться от справочника значений
            field.help_text = hint
            # Класс условный, а не по типу виджета: конвертеры crispy такое
            # не выражают. «field» дописывать не нужно — crispy увидит его в
            # строке и второй раз не добавит.
            field.widget.attrs["class"] = "field field--locked"

    def _initial(self):
        """Начальные значения формы — одинаковые для показа и для отправки.

        Для запертых полей это не удобство, а источник истины: значение
        ``disabled``-поля Django берёт именно отсюда.
        """
        # у всей группы одинаковые значения (Group) подставляются сразу
        initial = defaults(self.category) if self.created else {}

        # Замена — тот же компонент другого производителя: подгруппа,
        # корпус, номинал, температурный диапазон у неё те же. Поэтому
        # параметры списываются с основного компонента, как при заведении
        # по образцу, — заполнять их заново было бы переписыванием
        # соседней карточки вручную.
        #
        # Опознающие поля и Datasheet не переносятся (см. NOT_COPIED):
        # аналог на то и аналог, что артикул, производитель и документация
        # у него свои. Лишние ключи не мешают: в таблице замен нет полей
        # Allegro, и в форму они просто не попадут.
        for donor in (self.source, self.sample):
            if donor is not None:
                initial.update(sample_initial(donor))

        for name, (value, _) in self.locked.items():
            initial[name] = value
        return initial

    def build_form(self, data=None):
        """Собирает форму и сразу запирает поля.

        Запереть их нужно до проверки, а не перед показом. ``disabled``
        Django учитывает в ``is_valid()``: только там он подставляет
        значение из ``initial`` вместо присланного. Пока поле заперто лишь
        при отрисовке, браузер его не отправляет (disabled-поля не
        отправляются), проверка видит пустоту и записывает «---» — так
        Group и сбрасывалась при каждой правке.
        """
        form = self.get_form_class()(data, instance=self.object,
                                     initial=self._initial())
        self._lock_widgets(form)
        return form

    def render_form(self, request, form):
        return render(request, self.template_name, {
            "category": self.category,
            "form": form,
            "sections": group_fields(form),
            "object": self.object if self.object.pk else None,
            "source": self.source,
            "sample": self.sample,
            "oy_id": self.oy_id,
            "oy_id_hint": self.oy_id_hint,
        })

    def get_form_class(self):
        return build_form_class(self.category.model, self.category.table)

    def get(self, request):
        return self.render_form(request, self.build_form())

    def post(self, request):
        form = self.build_form(request.POST)
        if not form.is_valid():
            messages.error(request, _invalid_form_message(form))
            return self.render_form(request, form)

        created = self.created
        try:
            obj = form.save(commit=False)
            # OY ID формой не передаётся — его в ней нет. У новой записи он
            # назначается по нумерации, у существующей остаётся прежним.
            if self.oy_id:
                obj.oy_id = self.oy_id
            # остальные запертые поля доопределять не нужно: disabled-поля
            # Django заполняет из initial и присланные данные игнорирует.
            # Автор проставляется сам при создании и дальше не меняется:
            # это тот, кто завёл запись, а не последний правивший
            if created and not getattr(obj, "author", None):
                obj.author = request.user.get_username()
            obj.save()
        except DatabaseError as exc:
            messages.error(request, f"База отклонила запись: {exc}")
            return self.render_form(request, form)

        # сравнивается то, что в самом деле легло в базу, а не список
        # полей, которые форма считает изменёнными: при сохранении пустые
        # значения превращаются в «---», и форма об этом не знает
        record(obj, self.category.table, request.user, self.before)
        # подтверждённое совпадение — отдельное событие: запись завели,
        # зная, что похожая уже есть
        record_duplicate(obj, self.category.table, request.user,
                         form.confirmed_duplicates)

        messages.success(
            request,
            f"Компонент {obj.display_title()} "
            + ("добавлен." if created else "сохранён."))
        return redirect("components:detail", slug=self.category.slug, pk=obj.pk)


def _invalid_form_message(form):
    """Что сказать, когда форма не прошла проверку.

    Названия полей с ошибками помогают найти их в длинной форме: полей под
    сотню, и «проверьте форму» без подсказки означало бы просмотр всех.
    """
    labels = [str(form.fields[name].label or name)
              for name in form.errors if name in form.fields]
    if not labels:
        return "Не сохранено — проверьте форму."
    return "Не сохранено — проверьте поля: " + ", ".join(labels)


# ---- удаление ------------------------------------------------------------

@component_editor
def component_delete(request, slug, pk):
    category = category_or_404(slug)
    read_only = _read_only_redirect(request, category)
    if read_only is not None:
        return read_only

    obj = fetch(category, pk)

    # где компонент стоит на платах и сколько у него аналогов —
    # это узнают до удаления, а не после
    boards, board_rows = usage_summary(obj, category.table)
    analogs = _analog_count(category, obj)
    risky = bool(boards or analogs)

    if request.method == "POST":
        if risky and not request.POST.get("confirm"):
            messages.error(
                request,
                "Компонент используется — подтвердите удаление галочкой.")
        else:
            title = obj.display_title()
            # пишем до удаления: после него не останется ни значений,
            # ни ключа, по которому эту запись можно опознать
            record_deletion(obj, category.table, request.user)
            obj.delete()
            if board_rows:
                messages.warning(
                    request,
                    f"{board_rows} строк в составах плат остались без связи "
                    f"с библиотекой — теперь они показывают данные из файла.")
            messages.success(request, f"Компонент {title} удалён.")
            return redirect("components:list", slug=slug)

    return render(request, "components/confirm_delete.html", {
        "category": category,
        "object": obj,
        "boards": boards,
        "board_rows": board_rows,
        "analogs": analogs,
        "risky": risky,
    })


@fallback(0, "число аналогов по OY ID")
def _analog_count(category, obj):
    """Сколько записей в парной таблице делят с этой один OY ID."""
    pair = counterpart(category)
    oy_id = usable(getattr(obj, "oy_id", ""))
    if not pair or not oy_id:
        return 0
    return pair.model.objects.filter(oy_id=oy_id).count()


# ---- поиск ---------------------------------------------------------------

def _search_components(term):
    """Совпадения по всем таблицам компонентов: рабочим и заменам.

    Сам обход — в :mod:`components.lookup`, он общий с выбором компонента в
    состав платы. Здесь остаётся только показ: превью по группам и точное
    число совпадений.

    Точное число нужно лишь тогда, когда совпадений больше, чем помещается
    в превью: таблиц двадцать семь, и ``COUNT`` по каждой из них — это
    двадцать семь лишних запросов там, где ответ и так виден по длине
    превью.
    """
    results, total = [], 0
    for category, queryset, objects, has_more in matches(term, SEARCH_PREVIEW):
        count = queryset.count() if has_more else len(objects)
        total += count
        results.append({
            "category": category,
            "objects": objects,
            "count": count,
            "url": (reverse("components:list", args=[category.slug])
                    + "?" + urlencode({"q": term})),
        })
    # сначала рабочие группы, внутри каждой части — по числу совпадений
    results.sort(key=lambda r: (r["category"].replacement, -r["count"]))
    return results, total


def global_search(request):
    """Поиск по всем группам, а также по платам и их составам."""
    term = (request.GET.get("q") or "").strip()
    results, total = [], 0
    boards, boards_count = [], 0
    board_items, board_items_count = [], 0

    if term:
        boards, boards_count = search_boards(term)
        board_items, board_items_count = search_items(term)
        results, total = _search_components(term)
        total += boards_count + board_items_count

    return render(request, "components/search.html", {
        "term": term,
        "results": results,
        "total": total,
        "boards": boards,
        "boards_count": boards_count,
        "board_items": board_items,
        "board_items_count": board_items_count,
    })


# ---- история изменений ---------------------------------------------------

LOG_PAGE_SIZE = 50


def change_log(request):
    """Журнал изменений по всей библиотеке.

    В карточке видна история одного компонента, и этого не хватает в двух
    случаях. Первый — вопрос «кто и когда правил это на прошлой неделе»,
    когда неизвестно, какой именно компонент смотреть. Второй — удаления:
    карточки у удалённой записи нет, и до сих пор такие записи можно было
    увидеть только в админке.
    """
    filters = request.GET
    per_page = page_size(request)
    try:
        paginator = Paginator(log_queryset(filters), per_page)
        page = paginator.get_page(filters.get("page"))
        rows = with_authors(list(page.object_list))
        total = paginator.count
    except DatabaseError:
        page, paginator, rows, total = None, None, [], 0

    return render(request, "components/changes.html", {
        "page": page,
        "paginator": paginator,
        "rows": rows,
        "total": total,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "actions": ComponentChange.ACTIONS,
        "tables": [c.table for c in CATEGORIES.values()],
        "authors": log_authors(),
        "selected": {
            "action": filters.get("action", ""),
            "table": filters.get("table", ""),
            "author": filters.get("author", ""),
            "since": filters.get("since", ""),
            "until": filters.get("until", ""),
        },
    })


def component_change(request, pk):
    """Подробности одной правки: кто, когда и что именно поменял.

    Открывается из карточки в отдельной вкладке, поэтому здесь есть ссылка
    обратно на компонент — вернуться «назад» в новой вкладке некуда.

    Компонент к этому моменту могли удалить или переименовать: история
    хранится отдельно и переживает запись. Тогда показываем то, что знаем,
    и говорим, что компонента больше нет.
    """
    change = get_object_or_404(ComponentChange, pk=pk)
    with_authors([change])
    # «таблицы такой нет» и «запись уже удалили» — разные сообщения на
    # странице, поэтому разрешение отдаёт обе половины отдельно
    category, obj = resolve(change.component_table, change.component_id)

    return render(request, "components/change.html", {
        "change": change,
        "category": category,
        "object": obj,
    })


# ---- ревизия данных ------------------------------------------------------

@admin_only
def duplicates(request):
    """Ревизия данных: где в библиотеке задвоились записи."""
    check = request.GET.get("check", DEFAULT_CHECK)
    if check not in CHECKS:
        check = DEFAULT_CHECK
    term = (request.GET.get("q") or "").strip()
    groups, failed = find_duplicates(check, term)

    page = Paginator(groups, DUPLICATE_PAGE_SIZE).get_page(
        request.GET.get("page"))
    return render(request, "components/duplicates.html", {
        "check": check,
        "checks": CHECKS,
        "hint": CHECKS[check]["hint"],
        "term": term,
        "page": page,
        "total": len(groups),
        "records": sum(group["count"] for group in groups),
        "failed": failed,
    })
