"""Работа со строкой запроса: фильтры, сортировка, страницы.

Раньше то же самое делали три разных куска кода — ``_querystring`` в
представлениях и ``sort_url``/``replace_page`` в тегах шаблонов, — и
правило «страница сбрасывается при смене фильтра» приходилось повторять
в каждом. Теперь оно записано один раз, здесь.
"""

PAGE_PARAM = "page"

# Чем разделены значения одного фильтра в строке запроса: `?vendor=TDK|Murata`.
# Один параметр вместо повторяющегося — так ссылку проще прочитать и
# переслать. Значений с вертикальной чертой внутри в каталоге не бывает;
# если появятся, разделитель придётся менять здесь и только здесь.
VALUE_SEPARATOR = "|"


def values_of(params, key):
    """Значения одного фильтра из строки запроса.

    Понимает оба вида записи: ``?vendor=TDK|Murata`` — так отправляет
    страница, и ``?vendor=TDK&vendor=Murata`` — так отправит браузер сам,
    если скрипт не загрузился и форму отдал обычный ``<select multiple>``.
    """
    getlist = getattr(params, "getlist", None)
    chunks = getlist(key) if getlist else [params.get(key)]
    values = []
    for chunk in chunks:
        for value in (chunk or "").split(VALUE_SEPARATOR):
            value = value.strip()
            if value:
                values.append(value)
    return values


def with_params(params, **overrides):
    """Копия строки запроса с изменёнными параметрами.

    Пустое значение убирает параметр. Номер страницы сбрасывается всегда:
    после смены фильтра или сортировки прежняя страница почти наверняка
    показывает уже не то, что нужно.
    """
    updated = params.copy()
    for key, value in overrides.items():
        if value in (None, ""):
            updated.pop(key, None)
        else:
            updated[key] = value
    updated.pop(PAGE_PARAM, None)
    encoded = updated.urlencode()
    return f"?{encoded}" if encoded else "?"


def with_page(params, page):
    """Та же строка запроса, но с другим номером страницы."""
    updated = params.copy()
    updated[PAGE_PARAM] = page
    return f"?{updated.urlencode()}"


def toggle_sort(params, field):
    """Ссылка сортировки по столбцу: первый клик — по возрастанию, второй — наоборот."""
    same_field = params.get("sort") == field
    ascending = params.get("dir", "asc") == "asc"
    direction = "desc" if (same_field and ascending) else "asc"
    return with_params(params, sort=field, dir=direction)


def sort_state(params, field):
    """Как столбец отсортирован сейчас: ``asc``, ``desc`` или пусто."""
    if params.get("sort") != field:
        return ""
    return "desc" if params.get("dir") == "desc" else "asc"
