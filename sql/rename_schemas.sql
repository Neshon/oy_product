-- Переименование схемы Django:
--
--   app  ->  oy_system    то, что создаёт и ведёт Django: служебные
--                         таблицы, платы, конструктор выпадающих списков
--
-- Таблицы компонентов остаются в public и никуда не переезжают: всё, что
-- ходит в них без явного указания схемы — сторонний софт, представление
-- Parts, ручные запросы, — находит их там само. Раньше этот скрипт
-- переносил их в oy_component_lib; от этого отказались, а для баз, где
-- переезд уже случился, есть обратный скрипт sql/use_public_schema.sql.
--
-- Переименование схемы не трогает то, что внутри: таблицы, индексы,
-- ограничения и права ссылаются друг на друга по внутренним
-- идентификаторам, а не по имени схемы, и переезжают вместе с ней.
-- Отдельно чинить ничего не нужно.
--
-- Порядок действий:
--   1. остановите приложение и снимите резервную копию:
--        pg_dump -Fc -d oy_system_db -f before_rename.dump
--      (если база ещё не переименована — -d postgres)
--   2. psql -d <база> -f sql/rename_schemas.sql
--   3. в .env: POSTGRES_SCHEMA=oy_system,public
--   4. python manage.py check_schema — первой строкой напечатает схемы
--      в поиске и покажет, в какой схеме нашлась каждая таблица
--
-- Скрипт идемпотентный: схема, уже переименованная, пропускается.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'oy_system') THEN
        RAISE NOTICE 'схема oy_system уже есть — пропускаю';
    ELSIF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app') THEN
        RAISE NOTICE 'схемы app нет — пропускаю';
    ELSE
        ALTER SCHEMA app RENAME TO oy_system;
        RAISE NOTICE 'схема app переименована в oy_system';
    END IF;
END $$;

COMMIT;

-- Проверка результата:
-- SELECT table_schema, count(*) FROM information_schema.tables
-- WHERE table_schema IN ('public', 'oy_system') GROUP BY 1;
