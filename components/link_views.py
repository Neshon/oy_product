"""Внешние ссылки на компоненты: импорт файлом и подтверждение по одной.

Отдельный модуль потому, что это самостоятельный раздел со своей логикой
сопоставления (``components.links``), а не часть работы со списком
компонентов, рядом с которой он раньше лежал.
"""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render

from .forms import LinkImportForm
from .links import LinkFileError, read_rows, resolve_rows, save_links
from .matching import usable
from .permissions import component_editor
from .refs import resolve


@component_editor
def link_add(request):
    """Заводит одну ссылку — по кнопке «Добавить» рядом с предположением.

    Предположение потому и предположение, что решает человек: страница
    импорта такие строки не записывает, а эта кнопка добавляет ровно одну,
    ту, которую подтвердили.

    Отвечает JSON, если позвали из браузера скриптом, и обычным
    перенаправлением, если скрипты отключены.
    """
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def answer(ok, message):
        if wants_json:
            return JsonResponse({"ok": ok, "message": message},
                                status=200 if ok else 400)
        (messages.success if ok else messages.error)(request, message)
        return redirect(request.META.get("HTTP_REFERER")
                        or "components:link-import")

    if request.method != "POST":
        return answer(False, "Так ссылку не добавить.")

    table = (request.POST.get("component_table") or "").strip()
    url = (request.POST.get("url") or "").strip()

    try:
        pk = int(request.POST.get("component_id") or "")
    except (TypeError, ValueError):
        return answer(False, "Некорректный ключ компонента.")

    # компонент могли удалить, пока смотрели результаты импорта: категория
    # есть, а записи уже нет — это разные ответы человеку
    category, obj = resolve(table, pk)
    if category is None or not url:
        return answer(False, "Не указано, к какому компоненту вести ссылку.")
    if obj is None:
        return answer(False, "Компонент не найден — возможно, его удалили.")

    if "tracker_url" not in category.field_names:
        return answer(False, f"В таблице {category.table} нет колонки "
                             f"«Tracker URL» — выполните sql/add_tracker_url.sql.")

    previous = usable(obj.tracker_url)
    if previous == url:
        return answer(True, f"Эта ссылка у {obj.display_title()} уже стоит.")

    obj.tracker_url = url
    obj.save(update_fields=["tracker_url"])

    if previous:
        # колонка одна: прежняя ссылка не остаётся рядом, а вытесняется
        return answer(True, f"Ссылка у {obj.display_title()} заменена. "
                            f"Была: {previous}")
    return answer(True, f"Ссылка добавлена к {obj.display_title()}.")


@component_editor
def link_import(request):
    """Импорт ссылок на компоненты из CSV через браузер.

    Показывает, что сопоставилось, а что нет: список ненайденных — главный
    результат, по нему видно, каких компонентов в библиотеке ещё нет или
    где артикул записан иначе.
    """
    form = LinkImportForm(request.POST or None, request.FILES or None)
    result = None

    if request.method == "POST" and form.is_valid():
        try:
            rows = read_rows(form.cleaned_data["file"])
        except LinkFileError as exc:
            form.add_error("file", str(exc))
        else:
            result = _import_result(request, form, rows)

    return render(request, "components/link_import.html",
                  {"form": form, "result": result})


def _import_result(request, form, rows):
    """Сопоставляет строки файла и, если просили, записывает ссылки."""
    matched, unmatched, already = resolve_rows(rows)
    result = {
        "total": len(rows),
        "matched": matched,
        "unmatched": unmatched,
        # уже заведённые в списки не попадают: при повторной загрузке
        # файла показывать нужно то, что осталось сделать
        "already": already,
        "links": sum(len(item["targets"]) for item in matched),
        # одна задача может попасть сразу в несколько записей — например,
        # в компонент и его аналог с тем же артикулом
        "many": [item for item in matched if len(item["targets"]) > 1],
        "written": False,
    }

    if form.cleaned_data["dry_run"]:
        messages.info(request, "Пробный проход — в базу ничего не записано.")
        return result

    filled, replaced = save_links(matched,
                                  source=form.cleaned_data["file"].name)
    result.update(written=True, filled=filled, replaced=replaced)
    messages.success(request, f"Ссылок проставлено: {filled}.")
    if replaced:
        # колонка одна: новая ссылка вытеснила прежнюю, и это стоит
        # заметить — вдруг ту заводили руками
        messages.warning(request,
                         f"Заменено ранее стоявших ссылок: {replaced}.")
    return result
