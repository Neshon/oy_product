"""Настройки проекта «Библиотека компонентов» (Django 6.1, Python 3.14)."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# .env читается вручную, чтобы не тянуть зависимость ради трёх строк
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _value = _line.partition("=")
        os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


DEV_SECRET_KEY = "dev-only-insecure-key-change-me"
# заглушки, с которыми в продакшен выходить нельзя: и та, что зашита здесь,
# и та, что лежит в .env.example и уезжает в .env при копировании
PLACEHOLDER_SECRET_KEYS = {DEV_SECRET_KEY, "change-me-please", ""}

SECRET_KEY = env("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# Ключ по умолчанию годится только для разработки: он лежит в репозитории,
# и с ним чужой может подписать себе сессию администратора. Молча запуститься
# с ним в продакшене нельзя — падаем сразу и понятно.
if not DEBUG and SECRET_KEY.strip() in PLACEHOLDER_SECRET_KEYS:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY не задан или оставлен заглушкой, а DEBUG "
        "выключен. Сгенерируйте ключ:\n"
        "  python -c \"import secrets; print(secrets.token_urlsafe(64))\"\n"
        "и положите его в переменную окружения DJANGO_SECRET_KEY.")

# За обратным прокси (nginx, traefik) Django видит http, даже когда снаружи
# https: протокол приезжает заголовком. Без этого редиректы и secure-куки
# ведут себя не так, как ожидается.
if env_bool("DJANGO_BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    # своя админка: конструктор списков отдельным разделом
    "components.admin_apps.ComponentsAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "crispy_forms",

    "components",
    "boards",
    "servers",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # раздаёт собранную статику прямо из gunicorn: отдельный nginx под это
    # заводить незачем, файлов десяток и они не меняются
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Весь сайт только для вошедших. Строго после AuthenticationMiddleware,
    # иначе request.user ещё не существует.
    #
    # Middleware, а не декораторы на представлениях: декоратор легко забыть
    # на новом представлении, и страница молча окажется открытой. Здесь
    # наоборот — закрыто всё, а открытое помечено login_not_required, и
    # все такие пометки собраны в одном месте, в config/urls.py.
    #
    # Раньше здесь стояла своя реализация (components/middleware.py) со
    # списком открытых путей и сравнением по префиксу. Django 5.1 привёз
    # ровно это штатно, вместе с login_not_required, — своё убрано.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "components.context_processors.navigation",
                "components.context_processors.permissions",
            ],
        },
    },
]

# --- PostgreSQL ---------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "oy_system_db"),
        "USER": env("POSTGRES_USER", "postgres"),
        "PASSWORD": env("POSTGRES_PASSWORD", "postgres"),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
        "OPTIONS": {
            # POSTGRES_SCHEMA может содержать несколько схем через запятую:
            # первая — где Django создаёт свои таблицы (oy_system), остальные —
            # где лежат таблицы компонентов (public).
            # См. sql/split_schema.sql и sql/rename_schemas.sql
            "options": (
                "-c search_path="
                + env("POSTGRES_SCHEMA", "oy_system,public")),
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Если у колонки id в таблицах компонентов нет DEFAULT/IDENTITY,
# поставьте True — id будет вычисляться как max(id)+1 при вставке.
COMPONENTS_ASSIGN_PK_MANUALLY = env_bool("COMPONENTS_ASSIGN_PK_MANUALLY", False)

# Сколько секунд держать в кэше значения фильтров, счётчики главной и
# справочник выпадающих списков (см. components/cache.py). Правки, сделанные
# через сайт, сбрасывают кэш сразу; этот срок отвечает за изменения, которые
# пришли в базу мимо нас. Ноль выключает кэш совсем.
COMPONENTS_CACHE_SECONDS = int(env("COMPONENTS_CACHE_SECONDS", "300"))

# Куда складывать этот кэш. По умолчанию — в память процесса: просто и
# ничего не требует. У такого кэша есть особенность, заметная именно при
# запуске в нескольких процессах (gunicorn): у каждого работника он свой,
# поэтому сброс после правки доходит только до того работника, который её
# принял, а до остальных — по истечении срока. Общий кэш это снимает:
#   DJANGO_CACHE_URL=redis://redis:6379/0
_cache_url = env("DJANGO_CACHE_URL", "")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _cache_url,
    } if _cache_url else {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "oy-components",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = env("DJANGO_LANGUAGE_CODE", "ru-ru")
TIME_ZONE = env("DJANGO_TIME_ZONE", "Europe/Moscow")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

# Загруженные файлы — изображения плат. Лежат отдельно от статики: статику
# собирает collectstatic и раздаёт whitenoise, а эти файлы приходят от
# людей, переживают пересборку образа и попадают в резервную копию.
# В контейнере каталог смонтирован томом (см. docker-compose.yml).
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))

# BOM-файлы разбираются на лету и на диск не сохраняются,
# поэтому достаточно ограничить размер загрузки
DATA_UPLOAD_MAX_MEMORY_SIZE = int(env("DJANGO_MAX_UPLOAD_SIZE", str(20 * 1024 * 1024)))
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # В продакшене — имена с хэшем и заранее пожатые копии: whitenoise
        # отдаёт их с длинным кэшем и без gzip на лету.
        #
        # При разработке хэша нет, адрес постоянный, и браузер держит
        # app.css в кэше — поправленные стили просто не видно. Поэтому своё
        # хранилище: дописывает к адресу время изменения файла
        # (config/staticfiles.py).
        "BACKEND": "config.staticfiles.VersionedStaticFilesStorage"
        if DEBUG else
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# Вход свой (config/urls.py), а не админский. Админская форма
# AdminAuthenticationForm отказывает всем, у кого не стоит «Статус
# персонала»: она спрашивает учётную запись персонала. Роли в библиотеке —
# обычные группы Django, is_staff у схемотехника и тополога нет, и войти
# через админскую форму они не могли вовсе.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "components:dashboard"
# После выхода — на справочник; он закрыт, поэтому видно форму входа с
# уже проставленным «куда шли».
LOGOUT_REDIRECT_URL = "components:dashboard"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)

# ---------------------------------------------------------------- формы ---
# Пакет шаблонов свой, а не bootstrap5: чужие классы пришлось бы
# переопределять поверх брендбука, а нам нужен ровно один шаблон строки
# формы с нашей разметкой (templates/oy/field.html).
CRISPY_ALLOWED_TEMPLATE_PACKS = ("oy",)
CRISPY_TEMPLATE_PACK = "oy"

# Какой класс получает поле по типу виджета. Здесь это заменяет три десятка
# строк вида attrs={"class": "field"} в формах: класс зависел только от типа
# виджета, а писался руками у каждого поля — и у части полей его забывали.
#
# Ключ — имя класса виджета в нижнем регистре, как его видит crispy.
CRISPY_CLASS_CONVERTERS = {
    "textinput": "field",
    "numberinput": "field",
    "emailinput": "field",
    "urlinput": "field",
    "passwordinput": "field",
    "dateinput": "field",
    "datetimeinput": "field",
    "timeinput": "field",
    "select": "field field--select",
    "nullbooleanselect": "field field--select",
    "selectmultiple": "field field--select",
    "textarea": "field field--area",
    "fileinput": "field",
    "clearablefileinput": "field",
    "multiplefileinput": "field",
    # флажку ширина во всю строку ни к чему, свой класс ему не нужен
    "checkboxinput": "",
}

# Таблицы компонентов неуправляемые, и в тестовой базе Django их не
# создаёт — а значит, всё, что с ними работает, тестировать нечем. Раннер
# заводит их схема-редактором; на боевую базу это не влияет.
TEST_RUNNER = "config.test_runner.UnmanagedModelsRunner"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}
