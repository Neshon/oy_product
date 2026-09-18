"""Мелкие хелперы шаблонов: ссылки сортировки и аккуратный вывод значений."""

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from ..querystring import sort_state as _sort_state
from ..querystring import toggle_sort, with_page, with_params

register = template.Library()

DASH = mark_safe('<span class="muted">—</span>')
LINK_MAX_LENGTH = 48


@register.simple_tag(takes_context=True)
def sort_url(context, field):
    """Ссылка на ту же страницу с переключённым направлением сортировки."""
    return toggle_sort(context["request"].GET, field)


@register.simple_tag(takes_context=True)
def sort_state(context, field):
    """Как столбец отсортирован сейчас: ``asc``, ``desc`` или пусто."""
    return _sort_state(context["request"].GET, field)


@register.simple_tag(takes_context=True)
def page_url(context, page):
    """Ссылка на другую страницу с сохранением фильтров и сортировки."""
    return with_page(context["request"].GET, page)


@register.simple_tag(takes_context=True)
def param_url(context, **params):
    """Та же страница с изменёнными параметрами; остальные сохраняются.

    ``{% param_url check="gbt" %}`` меняет одну проверку и не теряет
    введённый фильтр. Пустое значение убирает параметр:
    ``{% param_url q="" %}`` — это «сбросить поиск».

    Номер страницы сбрасывается — правило то же, что у
    ``querystring.with_params``: после смены отбора прежняя страница почти
    наверняка показывает уже не то.
    """
    return with_params(context["request"].GET, **params)


@register.filter
def cell(value):
    """Пустое значение показывается прочерком, ссылка — ссылкой."""
    if value is None or value == "":
        return DASH
    text = str(value)
    if text.startswith(("http://", "https://")):
        label = (text if len(text) <= LINK_MAX_LENGTH
                 else text[:LINK_MAX_LENGTH - 3] + "…")
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>',
                           text, label)
    return text


@register.filter
def wrap_refs(value):
    """Разрешает перенос строки в списке обозначений вида «C1,C4,C7».

    Без пробелов браузер видит это как одно длинное слово и не переносит
    его — ячейка либо растягивает таблицу, либо обрезается. <wbr> после
    каждой запятой даёт точку переноса, не меняя видимый текст.
    """
    if not value:
        return DASH
    return mark_safe(escape(value).replace(",", ",<wbr>"))
