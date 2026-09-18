"""Настройки gunicorn.

Значения берутся из окружения, чтобы их можно было подправить под сервер,
не пересобирая образ.
"""

import multiprocessing
import os


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# По умолчанию — по два работника на ядро плюс один, как советует сам
# gunicorn. Каждый держит своё соединение с базой (CONN_MAX_AGE=60),
# поэтому число работников — это ещё и число постоянных соединений:
# при небольшом лимите на стороне Postgres его стоит задать явно.
workers = _int("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1)

# Работников делаем многопоточными, и это не про производительность.
# Синхронный работник обслуживает соединение целиком и блокируется на
# чтении: клиент, который открыл соединение и молчит — сканер портов,
# внешняя проверка доступности, preconnect браузера, — держит работника до
# самого timeout, а арбитр считает его зависшим и убивает. В журнале это
# выглядит как «WORKER TIMEOUT» и трассировка с «no URI read», хотя ни
# одного запроса прочитано не было.
#
# При threads > 1 gunicorn берёт вместо sync класс gthread: там соединения
# обслуживает опрос сокетов, и молчащее никому не мешает.
#
# Плата — соединения с базой: их становится workers × threads, потому что
# CONN_MAX_AGE держит своё соединение на каждый поток. При небольшом
# max_connections в Postgres задайте оба числа явно.
threads = _int("GUNICORN_THREADS", 4)

# Импорт BOM разбирает файлы Excel и строит индекс по всем 27 таблицам
# компонентов; на большой библиотеке и пачке файлов это заметно дольше
# обычного запроса. Стандартных 30 секунд здесь не хватает.
timeout = _int("GUNICORN_TIMEOUT", 180)
graceful_timeout = _int("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int("GUNICORN_KEEPALIVE", 5)

# Постепенная замена работников: подстраховка от медленных утечек памяти
# при разборе больших файлов.
max_requests = _int("GUNICORN_MAX_REQUESTS", 1000)
max_requests_jitter = _int("GUNICORN_MAX_REQUESTS_JITTER", 100)

# приложение загружается до ветвления: словари реестра и категории
# считаются один раз, а не в каждом работнике
preload_app = True

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# в журнал доступа — адрес клиента из заголовка прокси, иначе там будет
# один и тот же адрес самого прокси
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "*")
access_log_format = '%({x-forwarded-for}i)s %(h)s "%(r)s" %(s)s %(b)s %(M)sms'
