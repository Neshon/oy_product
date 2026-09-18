"""Навигация доступна всем шаблонам без ручной передачи в контекст."""

from .permissions import (can_edit_boards, can_edit_components,
                          can_open_admin, is_admin)
from .registry import MAIN_CATEGORIES, REPLACEMENT_CATEGORIES


def navigation(request):
    return {
        "nav_categories": MAIN_CATEGORIES,
        "nav_replacements": REPLACEMENT_CATEGORIES,
    }


def permissions(request):
    """Права текущего пользователя — чтобы шаблоны не рисовали лишних кнопок."""
    user = getattr(request, "user", None)
    if user is None:
        return {}
    return {
        "can_edit_components": can_edit_components(user),
        "can_edit_boards": can_edit_boards(user),
        "is_admin": is_admin(user),
        "can_open_admin": can_open_admin(user),
    }
