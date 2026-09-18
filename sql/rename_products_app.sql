-- Переименование приложения: products -> servers
--
-- Django выводит имена таблиц из метки приложения, поэтому переименование
-- пакета в коде базу не трогает: таблицы остаются products_item и
-- products_bomline, а в django_migrations лежат строки с app = 'products'.
-- Если оставить как есть, при следующем migrate Django решит, что
-- приложение servers не мигрировано ни разу, и попробует создать таблицы
-- заново — поверх существующих данных.
--
-- Скрипт приводит базу в соответствие с кодом. Три вещи:
--   1. таблицы и их последовательности,
--   2. журнал миграций,
--   3. типы объектов (django_content_type).
--
-- Представление bom_edge чинить не нужно: PostgreSQL хранит ссылки на
-- таблицы по внутренним идентификаторам, а не по именам, и переписывает
-- определение представления при переименовании само. Имена ограничений и
-- индексов остаются старыми (products_bomline_parent_id_...) — они нигде
-- не используются по имени, и переименовывать их значило бы усложнить
-- скрипт ради косметики.
--
-- Порядок действий:
--   1. остановите приложение и снимите резервную копию:
--        pg_dump -Fc -d oy_system_db -f before_rename_app.dump
--   2. psql -d oy_system_db -f sql/rename_products_app.sql
--   3. запустите приложение — migrate накатит только то, чего ещё нет
--
-- Скрипт идемпотентный: то, что уже переименовано, пропускается.

BEGIN;

-- Таблицы Django живут в схеме oy_system (см. sql/rename_schemas.sql), а
-- psql по умолчанию смотрит только в public. Несуществующая схема в пути
-- поиска ошибкой не считается, поэтому строка годится и для баз, где
-- переезда схем ещё не было
SET search_path TO oy_system, public;

DO $$
DECLARE
    pair    text[];
    pairs   text[][] := ARRAY[
        ARRAY['products_item', 'servers_item'],
        ARRAY['products_bomline', 'servers_bomline']
    ];
    done    int := 0;
    skipped int := 0;
BEGIN
    FOREACH pair SLICE 1 IN ARRAY pairs LOOP
        IF to_regclass(pair[2]) IS NOT NULL THEN
            RAISE NOTICE 'таблица % уже есть — пропускаю', pair[2];
            skipped := skipped + 1;
        ELSIF to_regclass(pair[1]) IS NULL THEN
            RAISE NOTICE 'таблицы % нет — пропускаю', pair[1];
            skipped := skipped + 1;
        ELSE
            EXECUTE format('ALTER TABLE %I RENAME TO %I', pair[1], pair[2]);
            RAISE NOTICE 'таблица % -> %', pair[1], pair[2];
            done := done + 1;
        END IF;

        -- последовательность за таблицей не следует: у неё своё имя
        IF to_regclass(pair[1] || '_id_seq') IS NOT NULL
           AND to_regclass(pair[2] || '_id_seq') IS NULL THEN
            EXECUTE format('ALTER SEQUENCE %I RENAME TO %I',
                           pair[1] || '_id_seq', pair[2] || '_id_seq');
        END IF;
    END LOOP;

    RAISE NOTICE 'таблиц переименовано: %, пропущено: %', done, skipped;
END $$;

-- Журнал миграций. Строки с app = 'products' описывают ровно те миграции,
-- которые теперь лежат в пакете servers, — имена файлов не менялись
UPDATE django_migrations SET app = 'servers' WHERE app = 'products';

-- Типы объектов. Права (auth_permission) ссылаются на них по id, поэтому
-- переезжают вместе с ними и переназначать группы не нужно.
--
-- Строку трогаем только если метки servers ещё нет: пара
-- (app_label, model) уникальна, и вторая такая же уронила бы обновление
UPDATE django_content_type AS old
SET app_label = 'servers'
WHERE old.app_label = 'products'
  AND NOT EXISTS (
      SELECT 1 FROM django_content_type AS new
      WHERE new.app_label = 'servers' AND new.model = old.model);

COMMIT;
