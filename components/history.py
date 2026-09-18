"""История изменений компонента: что записывать и как показывать.

Правки в 27 таблиц компонентов приходят из двух мест — с формы на сайте и
из админки, — и записывать историю нужно в обоих. Поэтому сравнение «было —
стало» собрано здесь, а не в представлении: иначе один из двух путей рано
или поздно остался бы без истории, и та молча перестала бы быть полной.

Сравнивается состояние до правки со состоянием после, а не список полей,
которые форма считает изменёнными. Разница важна: при сохранении пустые
поля превращаются в ``---`` (см. ``components.forms``), а ``Created``
проставляется само. Форма об этом не знает, а история должна показывать то,
что в самом деле попало в базу.
"""

from datetime import date

from django.contrib.auth import get_user_model
from .db import fallback
from .models import ComponentChange

# Что в историю не пишем: суррогатный ключ пользователю ничего не говорит,
# а «Created» проставляется автоматически при заведении и потом не меняется.
IGNORED_FIELDS = frozenset({"id", "created"})

SITE = "сайт"
ADMIN = "админка"

# сколько правок показывать в карточке
CARD_LIMIT = 25


def snapshot(instance):
    """Значения всех полей записи — то, с чем потом сравнивать."""
    return {field.name: getattr(instance, field.name, None)
            for field in instance._meta.fields
            if field.name not in IGNORED_FIELDS}


def _text(value):
    """Значение в виде строки — такой, какой её видит пользователь.

    Пустое и заглушка ``---`` — для истории одно и то же: «не заполнено».
    Иначе замена пустой строки на ``---`` при сохранении попадала бы в
    историю как изменение, хотя для человека ничего не изменилось.
    """
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"---", "-", "?"} else text


def diff(before, after, model):
    """Список изменившихся полей: имя, подпись, было, стало."""
    fields = list(model._meta.fields)
    labels = {f.name: str(f.verbose_name) for f in fields}
    # порядок полей — как в модели, чтобы читалось так же, как карточка;
    # неизвестное поле (переименовали, убрали) уходит в конец
    order = {f.name: index for index, f in enumerate(fields)}
    last = len(order)

    changed = []
    for name, new_value in after.items():
        old_text, new_text = _text(before.get(name)), _text(new_value)
        if old_text == new_text:
            continue
        changed.append({"field": name, "label": labels.get(name, name),
                        "old": old_text, "new": new_text})

    changed.sort(key=lambda item: order.get(item["field"], last))
    return changed


def record(instance, table, user, before=None, source=SITE):
    """Записывает правку в историю. Возвращает запись или None.

    ``before`` — снимок до правки; пусто означает заведение новой записи, и
    тогда в историю попадают заполненные поля как «стало».

    История — не часть сохранения компонента: если записать её не удалось,
    сама правка уже в базе и терять её из-за этого нельзя. Поэтому ошибка
    базы здесь гасится.
    """
    before = before or {}
    after = snapshot(instance)
    changed = diff(before, after, type(instance))
    if not changed:
        return None

    action = (ComponentChange.UPDATED if before
              else ComponentChange.CREATED)
    return _save(table, instance.pk, user, action, source, changed)


def record_deletion(instance, table, user, source=SITE):
    """Записывает удаление компонента вместе с тем, что в нём было.

    Значения сохраняются здесь и больше нигде: карточки у удалённой записи
    не останется, а вопрос «что там было до удаления» возникает как раз
    после него. Смотреть — в админке, раздел «История изменений».

    Вызывается до ``delete()``, пока запись ещё цела и у неё есть ключ.
    """
    values = snapshot(instance)
    labels = {f.name: str(f.verbose_name) for f in instance._meta.fields}
    changes = [{"field": name, "label": labels.get(name, name),
                "old": _text(value), "new": ""}
               for name, value in values.items() if _text(value)]

    return _save(table, instance.pk, user, ComponentChange.DELETED, source,
                 changes)


def record_duplicate(instance, table, user, matches, source=SITE):
    """Записывает, что компонент заведён поверх уже похожего.

    Форма такие совпадения не пропускает молча — она отказывает и требует
    подтверждения (``components.forms``). Подтверждение бывает законным:
    иногда это правда разные детали. Но след должен остаться, иначе
    выяснить, откуда в библиотеке взялась пара близнецов, будет не по чему.

    Пишется отдельной записью, а не полем в записи о заведении: это разные
    события, и по списку истории видно оба.
    """
    changes = [{"table": match["category"].table,
                "id": match["obj"].pk,
                "title": match["obj"].display_title(),
                "reason": match.get("reason", "")}
               for match in matches]
    if not changes:
        return None

    return _save(table, instance.pk, user, ComponentChange.DUPLICATE, source,
                 changes)


@fallback(None, "запись в журнал изменений")
def _save(table, component_id, user, action, source, changes):
    """Общая запись в журнал. Ошибка базы гасится — см. record()."""
    return ComponentChange.objects.create(
        component_table=table, component_id=component_id,
        author=_username(user), action=action, source=source,
        changes=changes)


def _username(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    return user.get_username()


@fallback(dict, "имена сотрудников для журнала")
def author_names(logins):
    """``{логин: «Фамилия Имя»}`` для тех, у кого имя заполнено.

    Одним запросом на всю страницу, а не по запросу на строку.

    В журнале хранится логин, а не имя: логин у сотрудника один и не
    меняется, а фамилия может смениться — и тогда старые записи остались бы
    подписаны по-старому. Имя подставляется при показе, поэтому история
    всегда согласована с текущим списком пользователей.
    """
    logins = {login for login in logins if login}
    if not logins:
        return {}

    User = get_user_model()
    found = User.objects.filter(username__in=logins).values_list(
        "username", "first_name", "last_name")

    names = {}
    for login, first, last in found:
        full = f"{last} {first}".strip()
        if full:
            names[login] = full
    return names


def with_authors(changes):
    """Проставляет каждой записи ``author_display``.

    Если имя не заполнено или учётную запись удалили, остаётся логин: в
    журнале лучше показать логин, чем прочерк.
    """
    names = author_names(change.author for change in changes)
    for change in changes:
        change.author_display = names.get(change.author) or change.author
    return changes


def log_queryset(filters):
    """Записи журнала по фильтрам. Возвращает queryset, а не список.

    Постраничный показ читает из базы только свою порцию: записей в журнале
    со временем станет больше, чем во всей библиотеке — правок у компонента
    много, а компонент один.

    ``filters`` — обычный словарь из строки запроса; неизвестные и пустые
    значения игнорируются, поэтому чужой параметр в адресе ничего не ломает.
    """
    found = ComponentChange.objects.all()

    action = (filters.get("action") or "").strip()
    if action in dict(ComponentChange.ACTIONS):
        found = found.filter(action=action)

    table = (filters.get("table") or "").strip()
    if table:
        found = found.filter(component_table=table)

    author = (filters.get("author") or "").strip()
    if author:
        found = found.filter(author=author)

    since = _date(filters.get("since"))
    if since:
        found = found.filter(created__date__gte=since)

    until = _date(filters.get("until"))
    if until:
        # включительно: «по 5 сентября» человек понимает как «весь день»
        found = found.filter(created__date__lte=until)

    return found


def _date(value):
    """Дата из поля формы (``2026-09-05``) или None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def author_logins():
    """Логины, встречающиеся в журнале, по одному разу.

    ``order_by()`` здесь обязателен, и это не косметика. У журнала есть
    сортировка по умолчанию (``ordering = ("-created", "-id")``), и Django
    добавляет поля сортировки в сам запрос — рядом с автором. Тогда
    ``distinct`` считает различными строки, где автор один, а время правки
    разное, и сотрудник попадает в список столько раз, сколько правок
    сделал. Сброс сортировки оставляет в запросе один столбец, и повторы
    убирает уже база.

    Порядок здесь не нужен: вызывающий сортирует логины сам.
    """
    return (ComponentChange.objects
            .exclude(author="")
            .order_by()
            .values_list("author", flat=True)
            .distinct())


@fallback(list, "список авторов журнала")
def log_authors():
    """Логины, встречающиеся в журнале, с именами — для выпадающего списка.

    Отдаёт пары ``(логин, как показать)``. Список короткий: сотрудников
    единицы, а не тысячи.
    """
    logins = sorted(author_logins())
    names = author_names(logins)
    return [(login, names.get(login) or login) for login in logins]


@fallback(list, "история правок компонента")
def history(table, component_id, limit=CARD_LIMIT):
    """Последние правки компонента — для списка в карточке."""
    found = list(ComponentChange.objects
                 .filter(component_table=table, component_id=component_id)
                 [:limit])
    return with_authors(found)
