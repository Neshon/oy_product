-- Разделение базы на две схемы.
--
--   oy_system  — то, что создаёт и ведёт Django: служебные таблицы, платы,
--                конструктор выпадающих списков;
--   public     — таблицы компонентов, с которыми работает сторонний софт.
--                Django читает и пишет их, но никогда не создаёт и не
--                меняет структуру.
--
-- Схема Django раньше называлась app — см. sql/rename_schemas.sql. Таблицы
-- компонентов остаются в public: всё, что ходит в них без явного указания
-- схемы, находит их там само.
--
-- Порядок действий:
--   1. остановите приложение и снимите резервную копию:
--        pg_dump -Fc -d oy_system_db -f oy_system_db.dump
--   2. psql -d oy_system_db -f sql/split_schema.sql
--   3. в .env: POSTGRES_SCHEMA=oy_system,public
--   4. python manage.py check_schema   — покажет обе схемы и сверит таблицы
--
-- Скрипт идемпотентный: таблицы, уже переехавшие в oy_system, пропускаются.

\set app_schema oy_system
\set data_schema public
\set app_user :USER   -- при необходимости: psql -v app_user=django_user ...

BEGIN;

CREATE SCHEMA IF NOT EXISTS :app_schema;

DO $$
DECLARE
    t       text;
    src     text;
    moved   int := 0;
    skipped int := 0;
    -- всё, что создаёт Django: служебное, платы и справочник списков
    tables  text[] := ARRAY[
        'django_migrations', 'django_content_type', 'django_session',
        'django_admin_log',
        'auth_user', 'auth_group', 'auth_permission',
        'auth_user_groups', 'auth_user_user_permissions',
        'auth_group_permissions',
        'boards_board', 'boards_boardrevision', 'boards_boarditem',
        'oy_option_field', 'oy_option_value'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        SELECT n.nspname INTO src
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = t AND c.relkind = 'r'
          AND n.nspname IN ('oy_system', 'public')
        ORDER BY (n.nspname = 'oy_system') DESC
        LIMIT 1;

        IF src IS NULL THEN
            RAISE NOTICE 'таблицы % нет — пропускаю', t;
            skipped := skipped + 1;
        ELSIF src = 'oy_system' THEN
            RAISE NOTICE 'таблица % уже в oy_system', t;
            skipped := skipped + 1;
        ELSE
            EXECUTE format(
                'ALTER TABLE public.%I SET SCHEMA oy_system', t);
            moved := moved + 1;
        END IF;
    END LOOP;

    RAISE NOTICE 'перенесено: %, пропущено: %', moved, skipped;
END $$;

COMMIT;

-- Права: создавать объекты можно только в oy_system. В public
-- остаётся работа с данными, поэтому никакая миграция физически не изменит
-- там структуру.
GRANT USAGE, CREATE ON SCHEMA :app_schema TO :"app_user";
GRANT USAGE ON SCHEMA :data_schema TO :"app_user";
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA :data_schema TO :"app_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA :data_schema TO :"app_user";

-- Чтобы права распространялись и на таблицы, созданные позже владельцем схемы:
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public
--     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";

-- Проверка результата:
-- SELECT table_schema, count(*) FROM information_schema.tables
-- WHERE table_schema IN ('oy_system', 'public') GROUP BY 1;
