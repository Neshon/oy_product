-- Переименование базы: postgres -> oy_system_db
--
-- Запускается НЕ из переименовываемой базы — Postgres не даёт переименовать
-- ту, к которой вы подключены. Подключитесь к любой другой, например к
-- служебной template1:
--
--   psql -d template1 -f sql/rename_database.sql
--
-- И к переименовываемой базе не должно остаться других подключений:
-- остановите приложение и всё, что с ней работает. Скрипт это проверяет
-- и, если подключения есть, ничего не делает.
--
-- ОТДЕЛЬНО ПРО ИМЯ postgres. Это служебная база, которую создаёт сам
-- PostgreSQL, и к ней по умолчанию подключаются psql без -d, pg_dumpall,
-- pgAdmin, системы мониторинга и резервного копирования. Переименовав её,
-- вы уносите заодно точку входа, которой пользуются чужие инструменты.
-- Поэтому ниже, после переименования, создаётся новая пустая postgres —
-- ровно для них.
--
-- Если данные лежат не в служебной postgres, а в своей базе (в README и
-- прежних скриптах это components), передайте её имя:
--
--   psql -d template1 -v old_name=components -f sql/rename_database.sql
--
-- Порядок действий:
--   1. остановите приложение и снимите резервную копию:
--        pg_dump -Fc -d postgres -f before_rename.dump
--   2. psql -d template1 -f sql/rename_database.sql
--   3. в .env: POSTGRES_DB=oy_system_db
--   4. python manage.py check_schema
--
-- Скрипт идемпотентный: если база уже переименована, он это скажет и
-- ничего делать не будет.

\if :{?old_name}
\else
  \set old_name postgres
\endif

\if :{?new_name}
\else
  \set new_name oy_system_db
\endif

SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM pg_database WHERE datname = :'new_name')
            THEN 'false'
        WHEN NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'old_name')
            THEN 'false'
        WHEN (SELECT count(*) FROM pg_stat_activity
              WHERE datname = :'old_name' AND pid <> pg_backend_pid()) > 0
            THEN 'false'
        ELSE 'true'
    END AS can_rename,
    CASE
        WHEN EXISTS (SELECT 1 FROM pg_database WHERE datname = :'new_name')
            THEN format('база %s уже есть — переименование не нужно', :'new_name')
        WHEN NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'old_name')
            THEN format('базы %s нет — проверьте имя', :'old_name')
        WHEN (SELECT count(*) FROM pg_stat_activity
              WHERE datname = :'old_name' AND pid <> pg_backend_pid()) > 0
            THEN format('к базе %s есть другие подключения (%s) — закройте их',
                        :'old_name',
                        (SELECT count(*) FROM pg_stat_activity
                         WHERE datname = :'old_name'
                           AND pid <> pg_backend_pid()))
        ELSE format('переименовываю %s в %s', :'old_name', :'new_name')
    END AS reason,
    -- пересоздавать служебную базу нужно, только если уносим именно её
    CASE
        WHEN :'old_name' = 'postgres'
             AND NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'new_name')
             AND EXISTS (SELECT 1 FROM pg_database WHERE datname = 'postgres')
            THEN 'true'
        ELSE 'false'
    END AS recreate_postgres
\gset

\echo :reason

\if :can_rename
    ALTER DATABASE :"old_name" RENAME TO :"new_name";
\endif

-- Служебная база на прежнем месте — для psql без -d, pg_dumpall и всего
-- остального, что рассчитывает её найти. Пустая: данные уехали вместе
-- с переименованной.
\if :recreate_postgres
    CREATE DATABASE postgres;
    COMMENT ON DATABASE postgres IS 'default administrative connection database';
\endif

-- Проверка результата:
-- SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY 1;
