"""Платы: список, состав по ревизиям, импорт BOM.

Выгрузка состава вынесена в :mod:`boards.export`, сравнение ревизий —
в :mod:`boards.diff`.
"""

from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from components import lookup
from components.permissions import board_editor
from components.refs import resolve
from components.registry import get_category
from servers.boards_bridge import sync_board

from .diff import revision_diff
from .export import exporter
from .search import revision_match
from . import checklists
from .forms import (BoardForm, BoardItemForm, BoardRevisionCreateForm,
                    BoardRevisionForm, BomUploadForm, ChecklistForm)
from .importer import BomParseError, parse_bom
from .linking import MATCH_PICK, build_index, component_values, link_items
from .models import BOARD_TYPES, Board, BoardItem, BoardRevision
from .pn import canonical
from .revisions import parse_pn, sort_key
from .search import items_queryset

PAGE_SIZE = 50
ITEM_PAGE_SIZE = 50

# Сколько компонентов показывать при выборе в состав. Постраничного вывода
# здесь нет намеренно: каждая страница — это запрос в каждую из 27 таблиц,
# а ищут тут конкретный артикул, а не листают библиотеку. Когда совпадений
# больше, дешевле уточнить запрос, и страница об этом прямо говорит.
LIBRARY_LIMIT = 50


def item_search(request):
    """Полный список строк состава, найденных по запросу.

    Раздел «составы плат» в глобальном поиске (components:search) показывает
    только первые несколько совпадений; эта страница — то же самое без
    ограничения, с постраничным выводом, как и список плат. Пагинация здесь
    работает по queryset, а не по готовому списку: страница читает из базы
    только свою порцию строк, даже если совпадений тысячи.
    """
    term = (request.GET.get("q") or "").strip()
    items = items_queryset(term) if term else BoardItem.objects.none()

    page = Paginator(items, ITEM_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "boards/item_search.html",
                 {"page": page, "term": term})


def board_list(request):
    term = (request.GET.get("q") or "").strip()
    board_type = (request.GET.get("type") or "").strip()

    boards = (Board.objects.select_related("current_revision").with_counts())
    if term:
        # номер могут набрать и с точками, и без: в базе он хранится без
        # них, поэтому ищем по обоим написаниям
        plain = canonical(term)
        boards = boards.filter(
            Q(base_pn__icontains=term) | Q(base_pn__icontains=plain)
            | Q(name__icontains=term)
            # номера и децимальные живут у ревизий; какие именно поля —
            # в boards/search.py, список общий с глобальным поиском
            | revision_match(term)).distinct()
    if board_type:
        boards = boards.filter(board_type=board_type)

    page = Paginator(boards, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "boards/list.html", {
        "page": page, "term": term,
        "board_type": board_type, "board_types": BOARD_TYPES})


def _group_by_position(items):
    """Позиция и её замены идут одной группой."""
    groups, current = [], None
    for item in items:
        if item.is_main or current is None:
            current = {"main": item if item.is_main else None,
                       "substitutes": [] if item.is_main else [item],
                       "position": item.position}
            groups.append(current)
        else:
            current["substitutes"].append(item)
    return groups


def board_detail(request, pk):
    """Карточка платы: сведения и список ревизий.

    Состава здесь нет намеренно. Плата — это модель: у неё назначение, тип
    и перечень ревизий, а состав всегда принадлежит конкретной ревизии.
    Показывать на одной странице и то и другое значит смешивать два
    уровня — читающий перестаёт понимать, к чему относится таблица.
    """
    board = get_object_or_404(
        Board.objects.select_related("current_revision"), pk=pk)
    # порядок ревизий — по счётчику из номера, а не по времени загрузки
    revisions = sorted(board.revisions.all(), key=sort_key, reverse=True)

    # прежние ссылки вида ?rev=2 ведут теперь на страницу ревизии
    number = request.GET.get("rev")
    if number:
        chosen = next((r for r in revisions if str(r.number) == number), None)
        if chosen is None:
            raise Http404("Такой ревизии нет")
        return redirect(chosen.get_absolute_url())

    return render(request, "boards/detail.html", {
        "board": board,
        "revisions": revisions,
        "current": board.current_revision,
    })


def revision_detail(request, pk, number):
    """Страница ревизии: своя карточка и свой состав из BOM."""
    board = get_object_or_404(
        Board.objects.select_related("current_revision"), pk=pk)
    revision = _revision_or_404(board, number)
    # Чек-листы читаются из поля ревизии, запроса к базе не делают: раньше
    # на ту же страницу уходило три — строки, заполненные и всего.
    done, total = checklists.progress(revision)

    return render(request, "boards/revision.html", {
        "board": board,
        "revision": revision,
        # состав живёт на своей странице, здесь нужны только счётчики
        "item_count": revision.item_count,
        "position_count": revision.position_count,
        "checklists": checklists.groups_for(revision),
        "checklist_done": done,
        "checklist_total": total,
    })


def revision_bom(request, pk, number):
    """Состав ревизии: строки BOM и отличия от предыдущей ревизии.

    Отдельной страницей: в BOM бывает под тысячу строк, и карточка вместе с
    ними превращалась в ленту, где ни реквизиты прочитать, ни состав
    просмотреть.
    """
    board = get_object_or_404(
        Board.objects.select_related("current_revision"), pk=pk)
    revisions = sorted(board.revisions.all(), key=sort_key, reverse=True)
    revision = _revision_or_404(board, number)

    # состав показывается как он записан в BOM: значения из библиотеки не
    # подставляются, поэтому и читать её здесь не нужно
    items = list(revision.items.all())

    # выгрузка отдаёт то, что было в файле: это документ, а не витрина
    export = exporter(request.GET.get("export"))
    if export is not None:
        return export(board, revision, items,
                      username=request.user.get_username())

    # предыдущая ревизия — предшествующий по ревизии, а не по времени загрузки
    position = revisions.index(revision) if revision in revisions else -1
    previous = (revisions[position + 1]
                if 0 <= position and position + 1 < len(revisions) else None)

    return render(request, "boards/bom.html", {
        "board": board,
        "revision": revision,
        "previous": previous,
        "groups": _group_by_position(items),
        "item_count": len(items),
        # состав уже в памяти — считаем по нему, а не отдельными запросами
        "position_count": sum(1 for i in items if i.is_main),
        "unlinked_count": sum(1 for i in items if not i.is_linked),
        "linked_count": sum(1 for i in items if i.is_linked),
        "diff": revision_diff(previous, items) if previous else None,
    })


@board_editor
def revision_checklist(request, pk, number):
    """Заполнение чек-листов ревизии.

    Все строки правятся одной формой: ходить по странице на каждый из
    двух десятков документов — работа ради работы.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    # Досоздавать строки больше не нужно: состав задан шаблоном, и строка
    # есть потому, что она в шаблоне. Пополнили шаблон — она появилась у
    # всех ревизий сразу, включая заведённые год назад.
    form = ChecklistForm(request.POST or None, revision=revision)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Чек-листы сохранены.")
        return redirect(revision.get_absolute_url())

    return render(request, "boards/checklist.html", {
        "board": board, "revision": revision,
        "form": form, "groups": form.groups})


@board_editor
def board_import(request):
    """Загрузка одного или нескольких BOM-файлов за раз."""
    form = BomUploadForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        uploads = sorted(form.cleaned_data["file"], key=lambda f: f.name)

        # индекс библиотеки строится один раз на всю пачку, а не на файл
        try:
            index = build_index()
        except DatabaseError as exc:
            messages.error(request, f"База недоступна: {exc}")
            return render(request, "boards/import.html", {"form": form})

        results = [_import_one(request, upload, index) for upload in uploads]
        loaded = [r for r in results if r["ok"]]
        failed = [r for r in results if not r["ok"]]

        if loaded:
            messages.success(
                request, f"Загружено файлов: {len(loaded)} из {len(results)}.")
        if failed:
            messages.error(
                request,
                "Не разобраны: " + ", ".join(r["name"] for r in failed))

        # один файл — сразу открываем его ревизию
        if len(results) == 1 and loaded:
            return redirect(loaded[0]["revision"].get_absolute_url())

        return render(request, "boards/import.html",
                      {"form": BomUploadForm(), "results": results})

    return render(request, "boards/import.html", {"form": form})


def _import_one(request, upload, index):
    """Разбирает и сохраняет один файл. Ошибка не прерывает остальные."""
    result = {"name": upload.name, "ok": False, "error": "", "revision": None,
              "unlinked": 0, "lines": 0}
    try:
        header, items = parse_bom(upload)
    except BomParseError as exc:
        result["error"] = str(exc)
        return result

    try:
        linked = link_items(items, index)
        revision = _save_revision(request, header, items)
    except DatabaseError as exc:
        result["error"] = f"база отклонила запись: {exc}"
        return result

    result.update(ok=True, revision=revision, lines=len(items),
                  unlinked=len(items) - linked)
    return result


@transaction.atomic
def _save_revision(request, header, items):
    """Сохраняет ревизию платы.

    Плата опознаётся по базовому номеру, ревизия — по полному: HSBP-5S01-02C
    и HSBP-5S01-02D это две ревизии одной платы, а не две платы. Повторная
    загрузка того же номера обновляет свою ревизию, а не плодит копии.

    Имя файла сюда больше не передаётся: хранить его перестали — одно и то
    же «BOM.xlsx» у десятка ревизий ничего не опознавало.
    """
    full_pn = header["oy_pn"]
    base_pn, _, _ = parse_pn(full_pn)
    username = request.user.get_username()

    board = Board.objects.filter(base_pn=base_pn).first() or Board(base_pn=base_pn)
    board.apply_pn(full_pn)
    # шапка BOM у платы не хранится: она своя у каждой ревизии
    board.imported_by = username
    board.save()

    revision = board.revisions.filter(oy_pn=full_pn).first()
    if revision is None:
        last = board.revisions.order_by("-number").first()
        revision = BoardRevision(board=board,
                                 number=(last.number + 1) if last else 1)
    revision.apply_pn(full_pn)
    revision.apply_header(header)
    # отметка ставится при каждой загрузке: спрашивают «когда состав
    # обновляли», а не «когда ревизия появилась»
    revision.remember_source(username)
    revision.save()
    # чек-листы заводятся сразу: пустой список честнее отсутствующего —
    # видно, что документы ждут, но их ещё нет
    # состав ревизии заменяется целиком: файл — источник истины
    revision.items.all().delete()
    BoardItem.objects.bulk_create(
        [BoardItem(revision=revision, **item) for item in items], batch_size=500)

    board.set_current(revision)
    # у платы должна быть позиция: в составе изделия она участвует как
    # позиция, а заводить её отдельной командой после каждого импорта —
    # лишний шаг, о котором забудут
    sync_board(board)
    return revision


@board_editor
def revision_create(request, pk):
    """Новая ревизия платы руками — когда BOM-файла ещё нет.

    Состав у такой ревизии пустой: он наполняется импортом BOM или
    построчно. Карточка и чек-листы заводятся сразу — ради них ревизия
    обычно и создают до файла.
    """
    board = get_object_or_404(Board, pk=pk)
    # request.FILES: в карточке ревизии загружают снимки платы
    form = BoardRevisionCreateForm(request.POST or None, request.FILES or None,
                                   board=board)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            revision = form.save(commit=False)
            revision.board = board
            revision.apply_pn(form.cleaned_data["oy_pn"])
            last = board.revisions.order_by("-number").first()
            revision.number = (last.number + 1) if last else 1
            # BOM у такой ревизии ещё не загружали: отметка о загрузке
            # остаётся пустой, и это правда, а не пропуск
            revision.save()

            # первая ревизия платы сразу становится текущим: иначе плата
            # осталась бы без состава, хотя ревизия у неё уже есть
            if board.current_revision_id is None:
                board.set_current(revision)
            sync_board(board)

        messages.success(request, f"Ревизия {revision.oy_pn} заведена.")
        return redirect(revision.get_absolute_url())

    return render(request, "boards/revision_form.html",
                  {"board": board, "revision": None, "form": form})


@board_editor
def revision_edit(request, pk, number):
    """Правка карточки ревизии."""
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    # request.FILES: в карточке ревизии загружают снимки платы
    form = BoardRevisionForm(request.POST or None, request.FILES or None,
                             instance=revision)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Карточка ревизии {revision.label} сохранена.")
        return redirect(revision.get_absolute_url())

    return render(request, "boards/revision_form.html",
                  {"board": board, "revision": revision, "form": form})


@board_editor
def revision_delete(request, pk, number):
    """Удаление ревизии вместе с его составом и чек-листами.

    Если удаляют текущая ревизия, текущим становится следующий по ревизии —
    плата не должна остаться без состава, пока у неё есть другие ревизии.
    Ссылка `Board.current_revision` обнулилась бы и сама (SET_NULL), но
    молча: список плат показал бы прочерк там, где данные есть.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)

    if request.method == "POST":
        was_current = revision.is_current
        label = revision.oy_pn or revision.label

        with transaction.atomic():
            revision.delete()
            if was_current:
                left = sorted(board.revisions.all(), key=sort_key, reverse=True)
                board.set_current(left[0] if left else None)

        messages.success(request, f"Ревизия {label} удалена.")
        return redirect(board.get_absolute_url())

    return render(request, "boards/revision_confirm_delete.html",
                  {"board": board, "revision": revision,
                   "checklist_done": checklists.progress(revision)[0]})


@board_editor
def revision_activate(request, pk, number):
    """Возврат к прежней ревизии: она снова становится текущей."""
    board = get_object_or_404(Board, pk=pk)
    revision = get_object_or_404(BoardRevision, board=board, number=number)
    if request.method == "POST":
        board.set_current(revision)
        messages.success(
            request, f"Текущей ревизией {board.base_pn} стала {revision.number}.")
    return redirect(revision.get_absolute_url())


@board_editor
def board_delete(request, pk):
    """Удаление платы вместе с ревизиями и позицией-двойником.

    На плату ссылается позиция из раздела изделий, и ссылка защищённая:
    без явного удаления позиции запрос падал бы с ProtectedError прямо в
    лицо. А если этой позицией пользуются составы изделий, удалять нельзя
    вовсе — иначе состав молча потеряет плату.
    """
    board = get_object_or_404(Board, pk=pk)
    item = twin_item(board)
    used_in = list(item.used_in.select_related("parent")) if item else []

    if request.method == "POST":
        if used_in:
            messages.error(
                request,
                "Плата входит в состав изделий — сначала уберите её оттуда: "
                + ", ".join(sorted({line.parent.oy_pn for line in used_in})))
            return redirect(board.get_absolute_url())

        name = board.base_pn
        with transaction.atomic():
            if item is not None:
                item.delete()
            board.delete()
        messages.success(request,
                         f"Плата {name} удалена вместе со всеми ревизиями.")
        return redirect("boards:list")

    return render(request, "boards/confirm_delete.html",
                  {"board": board, "item": item, "used_in": used_in})


# ---- ведение платы руками, без файла BOM ---------------------------------

@board_editor
def board_create(request):
    """Заводит плату. Ревизии к ней добавляются импортом BOM.

    Пустая ревизия здесь больше не создаётся: она существовала ради шапки,
    которую плата дублировала, а теперь шапка целиком принадлежит ревизии
    и браться ей неоткуда.
    """
    form = BoardForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            board = form.save(commit=False)
            # файла не было: плата заводится руками
            board.imported_by = request.user.get_username()
            board.save()
            sync_board(board)

        messages.success(request, f"Плата {board.base_pn} заведена. "
                                  f"Теперь загрузите её BOM.")
        return redirect(board.get_absolute_url())

    return render(request, "boards/board_form.html", {"form": form})


@board_editor
def board_edit(request, pk):
    """Правка карточки платы: номер, наименование, описание."""
    board = get_object_or_404(Board, pk=pk)
    # request.FILES: в карточке платы загружают изображения
    form = BoardForm(request.POST or None, request.FILES or None, instance=board)

    if request.method == "POST" and form.is_valid():
        board = form.save()
        sync_board(board)
        messages.success(request, f"Плата {board.base_pn} сохранена.")
        return redirect(board.get_absolute_url())

    return render(request, "boards/board_form.html",
                  {"form": form, "board": board})


def bom_url(revision):
    """Страница состава ревизии: туда возвращают правки строк BOM."""
    return reverse("boards:bom", args=[revision.board_id, revision.number])


def twin_item(board):
    """Позиция изделий, представляющая эту плату. Нет — значит None."""
    from servers.models import Item

    return Item.objects.filter(board=board).first()


def _revision_or_404(board, number=None):
    if number is None:
        revision = board.current_revision or board.revisions.first()
    else:
        revision = get_object_or_404(BoardRevision, board=board, number=number)
    if revision is None:
        raise Http404("У платы нет ни одной ревизии")
    return revision


@board_editor
def item_pick(request, pk, number):
    """Выбор компонента из библиотеки в состав ревизии.

    Ручной ввод артикула и поиск по библиотеке решают разные задачи.
    Артикул вводят, когда компонента в библиотеке ещё нет: строка
    сохранится как введена и останется помеченной ``?``. А когда он там
    есть — искать его глазами в карточке, чтобы потом переписать артикул в
    поле, значит делать работу, которую база уже сделала: опечатка в одном
    знаке даёт строку без связи, и замечают это не сразу.

    Поэтому здесь ищут по всем 27 таблицам сразу и выбирают запись, а
    поля строки заполняются из неё — см. :func:`item_edit`.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)

    term = (request.GET.get("q") or "").strip()
    category = get_category((request.GET.get("group") or "").strip())
    found, truncated = lookup.flat(term, LIBRARY_LIMIT,
                                   [category] if category else None)

    # Что из найденного уже стоит в этой ревизии. Повторно добавить не
    # запрещаем — один компонент честно бывает в составе дважды, под разными
    # позициями, — но сказать об этом надо: чаще это всё-таки промах.
    used = set(revision.items.exclude(component_id__isnull=True)
               .values_list("component_table", "component_id"))

    rows = [{"category": found_category,
             "object": obj,
             "used": (found_category.table, obj.pk) in used,
             "url": _pick_url(board, revision, found_category, obj)}
            for found_category, obj in found]

    return render(request, "boards/item_pick.html", {
        "board": board, "revision": revision,
        # в списке групп и таблицы замен: строкой S в состав ставят именно
        # их, и сузить поиск до одной такой таблицы — законное желание
        "term": term, "category": category,
        "categories": lookup.searchable(),
        "rows": rows, "truncated": truncated, "limit": LIBRARY_LIMIT,
    })


def _pick_url(board, revision, category, obj):
    """Форма новой строки с уже выбранным компонентом."""
    return (reverse("boards:item-create", args=[board.pk, revision.number])
            + "?" + urlencode({"from": category.slug, "id": obj.pk}))


def _picked(request, item):
    """Компонент, из которого заполняется строка: ``(категория, запись)``.

    Для новой строки он приходит из адреса (``?from=слаг&id=ключ``) — туда
    его кладёт страница выбора. Для уже сохранённой берётся её собственная
    связь, если она поставлена выбором: её карточку показывают рядом с
    формой. У строки из BOM-файла своей карточки может и не быть — тогда
    показывать нечего, но править строку это не мешает.

    ``(None, None)`` значит «компонента нет»: у новой строки это причина
    отправить человека выбирать, у сохранённой — просто отсутствие панели
    справа. Ошибочный или устаревший ключ в адресе даёт то же самое, а не
    ошибку.
    """
    if item.pk and item.component_match == MATCH_PICK:
        return resolve(item.component_table, item.component_id)

    slug = (request.POST.get("from") or request.GET.get("from") or "").strip()
    pk = (request.POST.get("id") or request.GET.get("id") or "").strip()
    category = get_category(slug)
    if category is None or not pk:
        return None, None

    try:
        return category, category.model.objects.filter(pk=pk).first()
    except (DatabaseError, ValueError, TypeError):
        return None, None


def _next_position(revision, kind):
    """Номер позиции для строки, у которой его не указали.

    У замены он тот же, что у основной строки: замена не занимает своей
    позиции в спецификации, она стоит под чужой. Поэтому ``S`` получает
    последний номер, а ``M`` — следующий за ним.
    """
    last = (revision.items.exclude(position__isnull=True)
            .order_by("-position").first())
    if last is None:
        return 1
    return (last.position if kind == BoardItem.SUBSTITUTE
            else last.position + 1)


@board_editor
def item_edit(request, pk, number, item_pk=None):
    """Заведение и правка строки состава.

    Новая строка заводится только из библиотеки: без выбранного компонента
    заполнять её нечем, поэтому такой запрос уходит на страницу выбора.
    Ручного ввода артикулов больше нет — см. :class:`BoardItemForm`.

    Правка открыта у любой строки, в том числе пришедшей из BOM-файла и не
    нашедшей себе карточки: править в ней можно то же самое — позицию,
    обозначения, количество, комментарий. Артикулы остаются такими, какими
    их выпустили в файле.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    item = (get_object_or_404(BoardItem, pk=item_pk, revision=revision)
            if item_pk else BoardItem(revision=revision))

    category, component = _picked(request, item)
    if item.pk is None and component is None:
        # Пришли на «новую строку» без компонента: либо по старой ссылке,
        # либо выбранную запись уже удалили. Отправлять на пустую форму
        # незачем — сохранить её всё равно будет нечем.
        messages.info(request, "Выберите компонент, который добавляете в состав.")
        return redirect("boards:item-pick", pk=board.pk, number=revision.number)

    form = BoardItemForm(request.POST or None, instance=item)

    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.revision = revision

        if item.position is None:
            item.position = _next_position(revision, item.kind)

        if item.pk is None:
            # Связь известна точно — компонент указал человек, искать её по
            # артикулам незачем. Поля переносятся здесь же и только здесь:
            # повторять перенос при каждой правке значило бы, что правка
            # количества молча подтягивает в выпущенный состав новое
            # описание из библиотеки, а состав это документ.
            for name, value in component_values(component).items():
                setattr(item, name, value)
            item.component_table = category.table
            item.component_id = component.pk
            item.component_match = MATCH_PICK

        item.save()
        messages.success(request, f"Позиция {item.position} сохранена.")
        return redirect(bom_url(revision))

    return render(request, "boards/item_form.html", {
        "form": form, "board": board, "revision": revision,
        "item": item if item.pk else None,
        "component": component, "category": category,
    })


@board_editor
def item_delete(request, pk, number, item_pk):
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    item = get_object_or_404(BoardItem, pk=item_pk, revision=revision)
    if request.method == "POST":
        position = item.position
        item.delete()
        messages.success(request, f"Позиция {position} удалена.")
    # возвращаем к составу той ревизии, где правили, а не к карточке платы
    return redirect(bom_url(revision))
