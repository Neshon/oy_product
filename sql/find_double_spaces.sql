-- Список таблиц здесь перечислен поимённо и повторяет components/models.py.
-- Новые скрипты так писать не нужно: список печатает реестр —
--   python manage.py make_column_sql --tables-only
--   python manage.py make_column_sql --column "<имя>" > sql/<файл>.sql
-- Этот файл оставлен как есть: он уже применён, и трогать применённое,
-- чтобы «стало красивее», дороже, чем оставить.

-- Ищет двойной пробел во всех текстовых колонках всех 27 таблиц
-- компонентов (14 рабочих + 13 замен). Справочник выпадающих списков
-- (oy_option_field, oy_option_value) и представление Parts не трогает —
-- это не таблицы компонентов.
--
-- Запуск:  psql -d oy_system_db -f sql/find_double_spaces.sql
--
-- Работает по схеме с таблицами компонентов. Если она называется иначе:
--   psql -d oy_system_db -v schema=public -f sql/find_double_spaces.sql

\if :{?schema}
\else
  \set schema public
\endif

SET search_path TO :schema;

DROP TABLE IF EXISTS _double_space_report;
CREATE TEMP TABLE _double_space_report (
    table_name text, column_name text, rows_affected bigint);

DO $$
DECLARE
    tbl text;
    col text;
    hits bigint;
    -- имена — как в components/models.py (db_table); PCB своих текстовых
    -- параметров не имеет, но участвует наравне с остальными
    tables text[] := ARRAY[
        'CAPACITOR', 'CLOCK', 'CONNECTOR', 'DIODE', 'FUSE', 'IC',
        'INDICATOR', 'INDUCTOR', 'MECHANICAL', 'PCB', 'POWER_IC',
        'RESISTOR', 'SWITCH', 'TRANSISTOR',
        'z_CAPACITOR', 'z_CLOCK', 'z_CONNECTOR', 'z_DIODE', 'z_FUSE', 'z_IC',
        'z_INDICATOR', 'z_INDUCTOR', 'z_MECHANICAL', 'z_POWER_IC',
        'z_RESISTOR', 'z_SWITCH', 'z_TRANSISTOR'
    ];
BEGIN
    FOREACH tbl IN ARRAY tables LOOP
        -- таблицы, которых в этой базе нет (например, ещё не создана
        -- какая-то из замен), пропускаем, а не падаем на ней
        IF to_regclass(format('%I.%I', current_schema(), tbl)) IS NULL THEN
            RAISE NOTICE 'таблицы % нет в схеме % — пропускаю', tbl, current_schema();
            CONTINUE;
        END IF;

        -- только текстовые колонки: числовые и даты двойного пробела не бывает
        FOR col IN
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = tbl
              AND data_type IN ('character varying', 'text', 'character')
        LOOP
            EXECUTE format('SELECT count(*) FROM %I WHERE %I LIKE %L',
                           tbl, col, '%  %')
            INTO hits;

            IF hits > 0 THEN
                INSERT INTO _double_space_report VALUES (tbl, col, hits);
            END IF;
        END LOOP;
    END LOOP;
END $$;

SELECT table_name AS "Таблица",
       column_name AS "Колонка",
       rows_affected AS "Строк с двойным пробелом"
FROM _double_space_report
ORDER BY table_name, column_name;
