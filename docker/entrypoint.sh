#!/bin/sh
# Что происходит перед запуском рабочего сервера.
#
# Порядок важен: сначала дожидаемся базы, потом накатываем миграции и только
# затем отдаём управление gunicorn. Контейнер приложения почти всегда
# стартует раньше, чем Postgres успевает принять соединения, и без ожидания
# первый запуск падал бы каждый раз.
set -e

: "${DJANGO_WAIT_FOR_DB:=60}"      # сколько секунд ждать базу, 0 — не ждать
: "${DJANGO_MIGRATE_ON_START:=true}"

wait_for_db() {
    [ "$DJANGO_WAIT_FOR_DB" -gt 0 ] || return 0

    echo "Жду базу (до ${DJANGO_WAIT_FOR_DB} с)…"
    waited=0
    while [ "$waited" -lt "$DJANGO_WAIT_FOR_DB" ]; do
        if python manage.py check --database default >/dev/null 2>&1; then
            echo "База отвечает."
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done

    # не молчим: пусть в журнале останется настоящая ошибка подключения,
    # а не просто «не дождался»
    echo "База не ответила за ${DJANGO_WAIT_FOR_DB} с:" >&2
    python manage.py check --database default >&2 || true
    return 1
}

wait_for_db

case "$DJANGO_MIGRATE_ON_START" in
    1|true|True|yes|on)
        # мигрируются только собственные таблицы Django: 27 таблиц
        # компонентов помечены managed = False, их миграции не касаются
        echo "Накатываю миграции…"
        python manage.py migrate --noinput
        ;;
    *)
        echo "Миграции пропущены (DJANGO_MIGRATE_ON_START=$DJANGO_MIGRATE_ON_START)."
        ;;
esac

exec "$@"
