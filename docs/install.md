# Установка и запуск

## Требования

* Python 3.14+
* PostgreSQL 18 с уже созданными таблицами компонентов
* Django 6.1, psycopg 3

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # укажите параметры своей базы
python manage.py check_schema       # сверяет модели с реальными колонками
python manage.py migrate            # только служебные таблицы Django
python manage.py createsuperuser
python manage.py runserver
```

Интерфейс — <http://127.0.0.1:8000/>, админка — <http://127.0.0.1:8000/admin/>.

Для локального запуска в `.env` достаточно поправить три вещи: закомментировать
`COMPOSE_FILE` (он нужен только Docker), поставить `POSTGRES_HOST=localhost` и
оставить `DJANGO_DEBUG=True`. С включённым `DEBUG` не нужен ни секретный ключ,
ни список доменов, статику раздаёт сам `runserver`, а ошибки видны на странице,
а не только в журнале.

База нужна своя, с таблицами компонентов: Django их не создаёт. Если базы под
рукой нет, поднимите её в Docker (следующий раздел) или залейте копию с
рабочего сервера — `pg_restore --no-owner --no-privileges`.

### Локально в Docker

Тот же образ, что и на сервере, — удобно, когда нужно проверить именно его,
вместе с базой и кэшем:

```bash
cp .env.example .env
docker compose up -d --build
```

В `.env` для локальной машины:

```
WEB_PORT=8000                 # 80 на Linux и macOS требует root
POSTGRES_BIND=127.0.0.1       # базу наружу не открываем
POSTGRES_PORT_PUBLISHED=5433  # если 5432 уже занят своим PostgreSQL
DJANGO_SECRET_KEY=<любая длинная строка>
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_SECURE_COOKIES=False
```

Сайт — <http://127.0.0.1:8000/>.

Учтите: `DJANGO_DEBUG=False` в контейнере задан жёстко, отладочный режим там
не включается. Поэтому ошибки выглядят обычной страницей 500, а подробности
— в `docker compose logs -f web`. Для разработки удобнее `runserver` из
раздела выше; Docker — чтобы проверить сборку и поведение боевого образа.

Снести всё вместе с базой: `docker compose down -v`.

### Настройки базы

Читаются из окружения или из файла `.env`:
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_SCHEMA`.

### Имена базы и схем

| Что | Имя | Что внутри |
|---|---|---|
| база | `oy_system_db` | всё вместе |
| схема | `public` | 27 таблиц компонентов и представление `Parts`; их читает и сторонний софт |
| схема | `oy_system` | то, что создаёт и ведёт Django: служебные таблицы, платы, конструктор списков |

Раньше это были база `postgres` и схема `app`
(Django). Переименование — в разделе «Переименование базы и схем» ниже.

### Разделение на схемы

Django создаёт собственные таблицы: служебные (`django_*`, `auth_*`), платы и
конструктор списков. Их удобно держать отдельно от таблиц компонентов, с
которыми работает сторонний софт.

```bash
pg_dump -Fc -d oy_system_db -f oy_system_db.dump   # сначала копия
psql -d oy_system_db -f sql/split_schema.sql       # создаст oy_system и перенесёт
```

Затем в `.env`:

```
POSTGRES_SCHEMA=oy_system,public
```

Схемы перечисляются в порядке поиска: первая — та, где Django создаёт свои
таблицы, дальше идут схемы с таблицами компонентов. Код менять не нужно,
значение уходит в `search_path` соединения. Если всё лежит в одной схеме,
достаточно указать её одну.

Что это даёт: пользователю Django можно выдать `CREATE` только в
`oy_system`, а в `public` оставить лишь работу с данными. Тогда
никакая миграция физически не изменит структуру таблиц компонентов — сейчас
это держится только на `managed = False`.

Проверить результат: `python manage.py check_schema` — первой строкой он
печатает схемы в поиске, а рядом с каждой таблицей показывает, в какой схеме
она найдена. Скрипт `sql/enable_id_autoincrement.sql` принимает имя схемы:
`psql -v schema=public -f sql/enable_id_autoincrement.sql`.

### Переименование базы и схем

Переезд выполнен. Порядок действий и подводные камни — в [истории переездов схемы](schema-history.md).

### Если компоненты уже переехали в oy_component_lib

Переезд выполнен. Порядок действий и подводные камни — в [истории переездов схемы](schema-history.md).

### Если вставка падает на колонке id

В схеме `id` — обычный `integer NOT NULL`. Когда у него нет `DEFAULT` или
`IDENTITY`, новая запись вставиться не сможет. Два пути:

1. **Починить базу (рекомендуется):**
   `psql -d oy_system_db -f sql/enable_id_autoincrement.sql`
2. **Обойтись без изменений схемы:** поставить `COMPONENTS_ASSIGN_PK_MANUALLY=True`
   в `.env`. Тогда при вставке id считается как `max(id) + 1` под
   `pg_advisory_xact_lock`, так что параллельные вставки не столкнутся.

---

[← к оглавлению](../README.md)
