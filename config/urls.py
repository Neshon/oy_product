from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from .health import healthz
from .media import media_file

# Сайт закрыт целиком: за это отвечает штатная LoginRequiredMiddleware
# (см. settings.MIDDLEWARE). Исключения помечены здесь, в таблице
# маршрутов, а не декораторами на самих представлениях — так видно сразу,
# что именно открыто, и список нельзя случайно разойтись с адресами.
#
# Их три, и каждое по необходимости: форма входа (иначе войти было бы
# некуда), выход и /healthz/ для Docker.
urlpatterns = [
    # проверка живости — раньше всего: у компонентов последний маршрут
    # ловит любой слаг и перехватил бы этот адрес
    path("healthz/", login_not_required(healthz), name="healthz"),

    # Вход свой, а не админский. Админская форма отказывает всем, у кого
    # не стоит «Статус персонала», — а роли в библиотеке это обычные
    # группы, и у схемотехника с топологом is_staff нет.
    path("accounts/login/",
         login_not_required(LoginView.as_view(
             template_name="login.html",
             # уже вошедшему форма ни к чему: возвращаем к справочнику
             redirect_authenticated_user=True)),
         name="login"),
    path("accounts/logout/",
         login_not_required(LogoutView.as_view()), name="logout"),

    # Изображения плат. Раньше маршрутов разделов: последний маршрут
    # компонентов ловит любой слаг и перехватил бы этот адрес. Почему
    # отдаёт Django, а не прокси, — в config/media.py
    path(f"{settings.MEDIA_URL.lstrip('/')}<path:path>", media_file,
         name="media"),

    path("admin/", admin.site.urls),
    # платы идут раньше по той же причине
    path("boards/", include("boards.urls")),
    path("servers/", include("servers.urls")),
    path("", include("components.urls")),
]
