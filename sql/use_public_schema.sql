-- Возврат таблиц компонентов в схему public.
--
--   oy_component_lib  ->  public    27 таблиц компонентов и представление
--                                   Parts; их читает и сторонний софт
--
-- Схема Django остаётся на месте: она называется oy_system и в public не
-- возвращается — смешивать её служебные таблицы с библиотекой компонентов
-- незачем, разделение как раз для этого и делалось.
--
-- Зачем откат. Всё, что ходит в таблицы компонентов без явного указания
-- схемы, полагается на public в search_path по умолчанию. Пока библиотека
-- лежала в oy_component_lib, каждому такому подключению нужно было
-- прописывать путь поиска отдельно. В public они находят таблицы сами.
--
-- Переименование схемы не трогает то, что внутри: таблицы, индексы,
-- ограничения, права и представление Parts ссылаются друг на друга по
-- внутренним идентификаторам, а не по имени схемы, и переезжают вместе с
-- ней. Отдельно чинить ничего не нужно.
--
-- Порядок действий:
--   1. остановите приложение и снимите резервную копию:
--        pg_dump -Fc -d oy_system_db -f before_public.dump
--   2. psql -d oy_system_db -f sql/use_public_schema.sql
--   3. в .env: POSTGRES_SCHEMA=oy_system,public
--   4. python manage.py check_schema — первой строкой напечатает схемы
--      в поиске и покажет, в какой схеме нашлась каждая таблица
--
-- Скрипт идемпотентный: если библиотека уже в public, он ничего не делает.
--
-- ПРО ПУСТУЮ public. В базе почти наверняка уже есть схема с таким именем —
-- её создаёт сам PostgreSQL, а sql/rename_schemas.sql предлагал завести её
-- заново после переезда. Занятое имя переименованию мешает, поэтому пустая
-- public удаляется. Если в ней что-то лежит, скрипт останавливается и
-- ничего не меняет: разбирать чужие объекты вслепую нельзя.

BEGIN;

DO $$
DECLARE
    leftovers int;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'oy_component_lib') THEN
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'public') THEN
            RAISE NOTICE 'схемы oy_component_lib нет, public на месте — уже сделано';
        ELSE
            RAISE EXCEPTION 'нет ни oy_component_lib, ни public — проверьте базу';
        END IF;
        RETURN;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'public') THEN
        SELECT count(*) INTO leftovers
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public';

        IF leftovers > 0 THEN
            RAISE EXCEPTION
                'в схеме public % объект(ов) — освободите имя вручную '
                'или перенесите их, иначе переименование затрёт чужое',
                leftovers;
        END IF;

        DROP SCHEMA public;
        RAISE NOTICE 'пустая public удалена — имя освобождено';
    END IF;

    ALTER SCHEMA oy_component_lib RENAME TO public;
    RAISE NOTICE 'oy_component_lib переименована в public';
END $$;

-- Права на схему возвращаем такими же, как у обычной public: PostgreSQL
-- заводит её именно с ними, а после переименования на месте public
-- оказалась схема со своими правами.
GRANT USAGE ON SCHEMA public TO PUBLIC;
COMMENT ON SCHEMA public IS 'standard public schema';

COMMIT;

-- Проверка результата:
-- SELECT table_schema, count(*) FROM information_schema.tables
-- WHERE table_schema IN ('public', 'oy_system') GROUP BY 1;
--
-- Сторонний софт, которому раньше прописывали путь поиска, теперь найдёт
-- таблицы и без него — но постоянный путь у роли, если он был выдан,
-- ссылается на несуществующую схему и его нужно снять:
--   ALTER ROLE <роль> RESET search_path;
