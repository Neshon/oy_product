from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from .health import healthz

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

    path("admin/", admin.site.urls),
    # платы идут раньше по той же причине
    path("boards/", include("boards.urls")),
    path("servers/", include("servers.urls")),
    path("", include("components.urls")),
]

# Изображения плат при разработке отдаёт сам Django. В продакшене этого не
# происходит и не должно: static() работает только при DEBUG, а файлы там
# раздаёт nginx — см. «Обратный прокси» в README. Возить байты через Python
# незачем, да и whitenoise загруженные файлы не видит: он знает только то,
# что собрал collectstatic.
#
# Вход для них обязателен, как и для страниц: в списке исключений выше их
# нет. В продакшене nginx отдаёт их кому угодно — это разница между средами,
# и она была здесь всегда.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
