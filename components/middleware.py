"""Весь сайт доступен только вошедшим пользователям.

Раньше просмотр списков и карточек был открыт всем: библиотека справочная,
и ограничивались только изменения. Теперь закрыт и просмотр — вход нужен на
любую страницу.

Проверка сделана посередине, а не декораторами на представлениях, по одной
причине: декоратор легко забыть на новом представлении, и страница молча
окажется открытой. Здесь наоборот — закрыто всё, а исключения перечислены
явным списком и видны в одном месте.

Права ролей это не отменяет: middleware отвечает только на вопрос «вошёл
или нет», а кому что можно менять — по-прежнему решают проверки из
``components.permissions``.
"""

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import resolve_url
from django.urls import reverse


class LoginRequiredMiddleware:
    """Отправляет неавторизованных на форму входа.

    Ставится после ``AuthenticationMiddleware``: до него ``request.user``
    ещё не существует.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.open_paths = self._open_paths()

    @staticmethod
    def _open_paths():
        """Адреса, которые обязаны работать без входа.

        Их всего три вида, и каждый — по необходимости, а не для удобства:
        сама форма входа (иначе войти было бы некуда), выход и проверка
        живости для Docker. Статика сюда не попадает: её раздаёт whitenoise,
        стоящий выше по цепочке, и до этой проверки запрос не доходит.
        """
        paths = {
            resolve_url(settings.LOGIN_URL),
            reverse("admin:login"),
            reverse("admin:logout"),
            reverse("healthz"),
        }
        # STATIC_URL нужен для runserver: в отладке статику отдаёт Django,
        # а не whitenoise
        if settings.STATIC_URL:
            paths.add(settings.STATIC_URL)
        return tuple(sorted(paths))

    def _is_open(self, path):
        return path.startswith(self.open_paths)

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is None or not user.is_authenticated) \
                and not self._is_open(request.path_info):
            # после входа вернём туда, куда шли, — вместе со строкой запроса:
            # ссылку на отфильтрованный список коллеги присылают друг другу
            return redirect_to_login(request.get_full_path(),
                                     resolve_url(settings.LOGIN_URL))
        return self.get_response(request)
