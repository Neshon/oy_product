# Библиотека компонентов — образ для сервера.
#
# Сборка в два этапа: колёса собираются отдельно, в рабочий образ попадают
# только готовые пакеты. Так в нём не остаётся компилятора и заголовков —
# образ меньше, и лишнего внутри нет.

# ---- сборка зависимостей --------------------------------------------------
FROM python:3.14-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ---- рабочий образ --------------------------------------------------------
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings

# curl нужен для HEALTHCHECK; больше в рабочем образе ничего не ставим
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# приложение работает не от root: писать ему в файловую систему нечего,
# BOM-файлы разбираются в памяти и на диск не ложатся
RUN useradd --create-home --uid 10001 app

COPY --from=build /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

WORKDIR /app
COPY --chown=app:app . .

# Статика собирается на сборке, а не при старте: она не зависит ни от базы,
# ни от настроек окружения, и собранная в образе даёт одинаковый результат
# на всех репликах. Ключ и DEBUG здесь одноразовые, в образ они не попадают:
# collectstatic требует их только чтобы настройки прочитались.
RUN DJANGO_DEBUG=False \
    DJANGO_SECRET_KEY=collectstatic-only \
    DJANGO_ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput --clear \
    && chown -R app:app /app/staticfiles

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz/ || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "--config", "docker/gunicorn.conf.py", "config.wsgi:application"]
