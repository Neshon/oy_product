"""Проверка живости для Docker и обратного прокси.

Отвечает по ``/healthz/``. Проверяется главное, без чего приложение
бесполезно, — что база отвечает: контейнер может подняться раньше неё или
пережить её перезапуск, и снаружи это должно быть видно, а не выясняться
на первом же открытии страницы.

Ответ намеренно короткий и без данных: адрес открыт всем, как и любая
проверка живости.
"""

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache


@never_cache
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        return JsonResponse({"ok": False, "database": str(exc)}, status=503)
    return JsonResponse({"ok": True})
