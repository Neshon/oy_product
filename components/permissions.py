"""Роли и права доступа.

Роли — обычные группы Django, их создаёт команда ``init_roles``:

* **Схемотехники** — ведут платы: импорт BOM, ревизии, удаление.
  Компоненты только смотрят;
* **Топологи** — только просмотр;
* **Библиотекари** — ведут библиотеку компонентов. Платы только смотрят;
* **администратор** (суперпользователь) — всё, включая отчёт по дублям.

Сайт целиком доступен только вошедшим — за это отвечает штатная
``django.contrib.auth.middleware.LoginRequiredMiddleware``; что открыто без
входа, перечислено в ``config/urls.py``. Здесь решается второй вопрос:
кому из вошедших что можно менять.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

ROLE_ENGINEER = "Схемотехники"
ROLE_TOPOLOGY = "Топологи"
ROLE_LIBRARIAN = "Библиотекари"

ROLES = {
    ROLE_ENGINEER: "Ведут платы и BOM, компоненты только просматривают",
    ROLE_TOPOLOGY: "Только просмотр компонентов и плат",
    ROLE_LIBRARIAN: "Ведут библиотеку компонентов, платы только просматривают",
}


def _group_names(user):
    """Группы пользователя. Запрашиваются один раз на объект пользователя.

    Проверок за запрос несколько: контекст шаблонов спрашивает про все три
    роли сразу, плюс декоратор представления. Каждая из них уходила в базу
    отдельным ``EXISTS``, хотя ответ в пределах запроса не меняется.
    Пользователь живёт ровно один запрос, поэтому на нём и запоминаем.
    """
    if not user.is_authenticated:
        return frozenset()
    names = getattr(user, "_role_names", None)
    if names is None:
        names = frozenset(user.groups.values_list("name", flat=True))
        try:
            user._role_names = names
        except AttributeError:
            # экзотический объект пользователя без словаря атрибутов:
            # обойдёмся без запоминания, проверка всё равно верна
            pass
    return names


def _in_group(user, *names):
    return bool(_group_names(user) & frozenset(names))


def is_admin(user):
    return user.is_authenticated and user.is_superuser


def can_edit_components(user):
    return is_admin(user) or _in_group(user, ROLE_LIBRARIAN)


def can_edit_boards(user):
    return is_admin(user) or _in_group(user, ROLE_ENGINEER)


def can_view_duplicates(user):
    return is_admin(user)


def can_open_admin(user):
    """Пустит ли пользователя админка Django.

    Проверяется ``is_staff``, а не суперпользователь: в админку ходят и за
    конструктором выпадающих списков, и это работа библиотекаря, а не
    только администратора. Кто именно из сотрудников туда допущен, решает
    галочка «Статус персонала» — здесь мы её только повторяем, чтобы не
    показывать ссылку тем, кому админка ответит «у вас нет доступа».

    Права это не выдаёт: доступ в админку по-прежнему проверяет она сама.
    """
    return user.is_authenticated and user.is_staff


def require(test, message, fallback="components:dashboard"):
    """Пускает по проверке; иначе — на вход или назад с объяснением.

    Отличие от ``user_passes_test``: вошедшего пользователя без прав не
    отправляем на форму входа — он уже вошёл, повторный вход не поможет.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if test(request.user):
                return view(request, *args, **kwargs)
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            messages.warning(request, message)
            return redirect(request.META.get("HTTP_REFERER") or fallback)
        return wrapper
    return decorator


component_editor = require(
    can_edit_components,
    "Изменять компоненты могут библиотекари и администратор.")

board_editor = require(
    can_edit_boards,
    "Изменять платы могут схемотехники и администратор.")

admin_only = require(
    is_admin, "Этот раздел доступен только администратору.")
