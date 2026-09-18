# Развёртывание

## Развёртывание в Docker

```bash
git clone <репозиторий> oy-components && cd oy-components
cp .env.example .env          # см. «Что обязательно заполнить» ниже
docker compose up -d --build
docker compose exec web python manage.py init_roles
docker compose exec web python manage.py createsuperuser
```

Сайт открывается по адресу сервера: `http://<IP>/`. Приложение публикуется
наружу само, статику раздаёт тоже само — отдельный обратный прокси при входе
по IP не нужен, сертификат на голый адрес всё равно не выпустить. Появится
домен и https — прокси добавляется в любой момент, см. «Обратный прокси».

### Что внутри

| Сервис | Зачем |
|---|---|
| `web` | gunicorn с приложением; статику раздаёт сам (whitenoise), слушает 80 |
| `redis` | общий кэш для всех работников gunicorn |
| `db` | PostgreSQL; поднимается, если подключён `docker-compose.postgres.yml` |

База вынесена в отдельный файл, потому что вариантов два и они
несовместимы.

**База в контейнере** — файл `docker-compose.postgres.yml`. В `.env.example`
он подключён строкой `COMPOSE_FILE`, поэтому достаточно обычного
`docker compose up -d`. Данные лежат в томе `pgdata`, порт 5432 открыт
наружу — к базе подключается сторонний софт. Пустую базу нужно наполнить —
см. «База в контейнере» ниже.

**База внешняя** (на хосте вне Docker или на другом сервере) — закомментируйте
`COMPOSE_FILE` в `.env` и укажите адрес в `POSTGRES_HOST`. Для базы на самом
сервере это `host.docker.internal`, и тогда нужно раскомментировать
`extra_hosts` у сервиса `web` в `docker-compose.yml`.

### База в контейнере

27 таблиц компонентов Django не создаёт — их ведёт не он. Свежий контейнер
поднимется с пустой базой, и сайт покажет нули. Данные заливаются один раз,
с рабочей копии:

```bash
# 1. снять копию там, где данные лежат сейчас
pg_dump -Fc -d postgres -f library.dump

# 2. поднять только базу и дождаться готовности
docker compose up -d db
docker compose ps db          # ждём healthy

# 3. залить
docker compose exec -T db pg_restore -U postgres -d oy_system_db \
    --no-owner --no-privileges < library.dump

# 4. если схемы ещё не переименованы — сделать это уже внутри
docker compose exec -T db psql -U postgres -d oy_system_db \
    < sql/rename_schemas.sql

# 5. поднять остальное
docker compose up -d
```

`--no-owner --no-privileges` нужны потому, что владелец и роли в копии — с
прежнего сервера, а в контейнере их нет. Права выдаются заново, после
восстановления.

Три вещи, которые меняются вместе с переездом базы в контейнер:

* **Сторонний софт, читающий `Parts`.** Раньше он ходил в базу напрямую.
  Теперь она внутри контейнера, и порт проброшен наружу — подробности и
  что с этим делать по части доступа, ниже, в разделе «База снаружи».
* **Резервные копии.** `pg_dump` с хоста больше не найдёт базу — снимайте
  через контейнер:
  `docker compose exec -T db pg_dump -U postgres -Fc oy_system_db > oy_system_db.dump`
* **Правило сортировки.** Оно задаётся один раз, при создании базы. Если на
  прежнем сервере было не то, что ставит образ по умолчанию, порядок строк
  в списках после переезда изменится. Посмотреть исходное:
  `SELECT datcollate FROM pg_database WHERE datname = current_database();`
  и задать его в `POSTGRES_INITDB_ARGS` **до первого запуска** контейнера —
  потом поможет только пересоздание тома.

### Что обязательно заполнить в .env

* `DJANGO_SECRET_KEY` — без него приложение с `DEBUG=False` не запустится и
  скажет об этом прямо. Сгенерировать:
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`;
* `DJANGO_ALLOWED_HOSTS` — IP сервера, а при наличии домена и он. Значение
  по умолчанию `*` годится только для разработки;
* `DJANGO_SECURE_COOKIES=False` — при входе по IP это обычный http, а с
  `True` браузер просто не отправит куку сессии, и войти не получится.
  Ставьте `True`, когда появится https;
* `POSTGRES_*` — имя базы, пользователь, пароль и `POSTGRES_SCHEMA`;
* `WEB_PORT` — порт сайта, по умолчанию 80.

`DJANGO_CSRF_TRUSTED_ORIGINS` при входе по IP на порт 80 можно оставить
пустым: запрос и страница с одного адреса, Django сверяет `Origin` с
`ALLOWED_HOSTS` сам. Заполнять нужно, когда появится https или нестандартный
порт — там со схемой: `https://library.example.ru`.

`DJANGO_DEBUG=False` и `DJANGO_CACHE_URL` проставляет сам
`docker-compose.yml` — в `.env` их дублировать не нужно.

Файл `.env` в образ не попадает (см. `.dockerignore`): он подключается на
запуске через `env_file`, поэтому образ одинаков для всех стендов.

### База снаружи

Порт 5432 опубликован на `0.0.0.0`, чтобы сторонний софт мог читать
представление `Parts` с других машин. Ограничить круг подключающихся внутри
контейнера нечем, поэтому это делается снаружи.

**Docker правит iptables в обход ufw.** Опубликованный контейнером порт
остаётся доступен, даже если `ufw status` показывает `5432 DENY`. Правило
нужно ставить в цепочку `DOCKER-USER`, а не в ufw:

```bash
# разрешить только своим, остальным закрыть
sudo iptables -I DOCKER-USER -p tcp --dport 5432 -s 192.168.1.0/24 -j ACCEPT
sudo iptables -I DOCKER-USER -p tcp --dport 5432 -j DROP
sudo apt install iptables-persistent   # чтобы правила пережили перезагрузку
```

Порядок важен: `-I` вставляет в начало, поэтому разрешающее правило нужно
добавлять **вторым**, чтобы оно оказалось выше запрещающего. Проверить:
`sudo iptables -L DOCKER-USER -n --line-numbers`.

Если весь доступ нужен только с самого сервера, проще не открывать порт
вовсе: `POSTGRES_BIND=127.0.0.1` в `.env`.

Стороннему софту заведите отдельную роль вместо суперпользователя — ему
нужно только чтение:

```sql
CREATE ROLE parts_reader LOGIN PASSWORD '<пароль>';
GRANT USAGE ON SCHEMA public TO parts_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO parts_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO parts_reader;
```

Если софту нужна и запись, добавьте `INSERT, UPDATE, DELETE` и права на
последовательности — но в схему `oy_system` доступ не выдавайте: там служебные
таблицы Django, чужому софту в них делать нечего.

Учтите, что этот софт скорее всего не указывает схему явно и полагается на
`public` в пути поиска. После переименования схем ему нужен свой путь:

```sql
ALTER ROLE parts_reader SET search_path = public;
```

### Обратный прокси

Нужен, только когда появятся домен и https. Тогда в `.env` поставьте
`WEB_BIND=127.0.0.1`, `WEB_PORT=8000`, `DJANGO_BEHIND_PROXY=True`,
`DJANGO_SECURE_COOKIES=True` и заполните `DJANGO_CSRF_TRUSTED_ORIGINS`.

```nginx
server {
    listen 443 ssl;
    server_name library.example.ru;

    ssl_certificate     /etc/letsencrypt/live/library.example.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/library.example.ru/privkey.pem;

    # пачка BOM-файлов; должно совпадать с DJANGO_MAX_UPLOAD_SIZE (20 МБ)
    client_max_body_size 20m;

    # изображения плат: отдаёт nginx, Django к ним не притрагивается
    location /media/ {
        alias /var/lib/docker/volumes/oy_media/_data/;
        expires 30d;
        add_header Cache-Control "public";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # импорт пачки BOM идёт дольше обычного запроса
        proxy_read_timeout 180s;
    }
}
```

Путь в `alias` — каталог тома `media` на хосте; точный путь показывает
`docker volume inspect`. Если nginx работает в контейнере, том подключается
к нему так же, как к `web`, и `alias` указывает на точку монтирования.

Три места, где значения должны совпадать по всей цепочке: размер загрузки
(`client_max_body_size` ↔ `DJANGO_MAX_UPLOAD_SIZE`), таймаут
(`proxy_read_timeout` ↔ `GUNICORN_TIMEOUT`) и заголовок `X-Forwarded-Proto`
(↔ `DJANGO_BEHIND_PROXY=True`). Разойдутся — импорт BOM будет обрываться на
середине без внятной ошибки.

### Что происходит при старте

`docker/entrypoint.sh` дожидается базы (до `DJANGO_WAIT_FOR_DB` секунд —
контейнер почти всегда стартует раньше, чем Postgres начинает принимать
соединения), накатывает миграции и передаёт управление gunicorn. Миграции
затрагивают только собственные таблицы Django: 27 таблиц компонентов
помечены `managed = False`, и `migrate` их не касается. Отключить накат:
`DJANGO_MIGRATE_ON_START=false`.

Статика собирается на этапе сборки образа, а не при запуске: она не зависит
ни от базы, ни от окружения, и собранная в образе одинакова на всех репликах.

Живость проверяется по `/healthz/` — адрес отвечает 200, пока база доступна,
и 503, когда нет. На нём же построен `HEALTHCHECK` образа, так что
`docker compose ps` показывает не «процесс запущен», а «приложение работает».

### Обслуживание

```bash
docker compose logs -f web                 # журнал
docker compose ps                          # состояние и healthcheck
docker compose exec web python manage.py check_schema   # сверить схему
docker compose pull && docker compose up -d --build      # обновление
```

Резервная копия — с базы, а не с контейнеров приложения: своих данных они не
хранят (BOM-файлы разбираются в памяти и на диск не ложатся).

```bash
# база в контейнере
docker compose exec -T db pg_dump -U postgres -Fc oy_system_db \
    > oy_system_db_$(date +%F).dump

# база внешняя
pg_dump -Fc -d oy_system_db -f oy_system_db_$(date +%F).dump
```

Том `pgdata` переживает `docker compose down`, но не `down -v`: ключ `-v`
удаляет тома вместе с данными. Копия должна быть свежей до того, как эта
команда понадобится.

### Версия образа

В `docker-compose.postgres.yml` версия закреплена до младшей —
`postgres:18.6`. Так на всех машинах поднимается одна и та же база, и
`docker compose pull` не подтягивает новую ветку молча.

Обновление внутри 18-й ветки выгрузки и восстановления не требует: меняете
тег, пересоздаёте контейнер, том остаётся прежним. Переход на 19-ю так не
пройдёт — это мажорная версия, нужен `pg_upgrade` или выгрузка с
восстановлением.

### Том с данными

Начиная с 18-й версии официальный образ держит кластер в подкаталоге с
номером версии — `/var/lib/postgresql/18/docker`, — а томом объявлен
родительский `/var/lib/postgresql`. Поэтому том подключён именно к нему, а
не к привычному `.../data`. Смысл в будущих обновлениях: кластеры соседних
версий лежат в одном томе рядом, и переход сводится к `pg_upgrade --link` —
почти мгновенному, вместо выгрузки и восстановления всей базы.

Со старым путём контейнер 18-й версии не поднимется, поэтому путь тома и тег
образа — одна пара: менять их можно только вместе.

Если у вас остался том от 17-й версии, поднять на нём 18-ю сменой одного
тега нельзя — это мажорный переход. Снимите `pg_dump` со старой версии,
поднимите 18-ю на чистом томе и восстановите.

### Работники и потоки

`GUNICORN_WORKERS` — процессы, `GUNICORN_THREADS` — потоки в каждом. Потоков
по умолчанию четыре, и это не про скорость: с одним потоком gunicorn берёт
синхронного работника, а тот обслуживает соединение целиком и блокируется на
чтении. Клиент, который открыл соединение и ничего не прислал — сканер
портов, внешняя проверка доступности, `preconnect` браузера, — держит
работника до самого `GUNICORN_TIMEOUT`, после чего арбитр считает его
зависшим и убивает:

```
[CRITICAL] WORKER TIMEOUT (pid:233)
[ERROR] Error handling request (no URI read)
...
[ERROR] Worker (pid:233) was sent SIGKILL! Perhaps out of memory?
```

Про память здесь неправда — это общая формулировка gunicorn на любой убитый
процесс; признак именно этого случая — `no URI read` и `WORKER TIMEOUT`
перед ней (при настоящем OOM запись оставит ядро, `dmesg -T | grep -i oom`).
Запросы при этом не теряются, ни один так и не был прочитан, но работник
уходит на перезапуск. При `threads > 1` gunicorn берёт класс `gthread`:
соединения обслуживает опрос сокетов, и молчащее никому не мешает.

Плата — соединения с базой: их `workers × threads`, потому что `CONN_MAX_AGE`
держит своё соединение на каждый поток. При 4 ядрах это 9 × 4 = 36; если
`max_connections` в Postgres невелик, задайте оба числа явно, например
`GUNICORN_WORKERS=5` и `GUNICORN_THREADS=4`.

Отдельно помогает не выставлять приложение в сеть напрямую: с nginx впереди
(`WEB_BIND=127.0.0.1`, см. «Обратный прокси») такие соединения поглощает
прокси, и до gunicorn они не доходят.

### Если работников gunicorn несколько

Кэш по умолчанию живёт в памяти процесса, и у каждого работника он свой:
сброс после правки доходит только до того работника, который её принял, а
до остальных — по истечении `COMPONENTS_CACHE_SECONDS`. На практике это
выглядит так: библиотекарь завёл компонент, обновил главную и не увидел
изменившийся счётчик. Поэтому в `docker-compose.yml` поднят `redis` и задан
`DJANGO_CACHE_URL` — кэш становится общим, и сброс виден сразу всем.

Если redis не нужен, уберите сервис и переменную: приложение вернётся к
кэшу в памяти, всё продолжит работать.

---

[← к оглавлению](../README.md)
