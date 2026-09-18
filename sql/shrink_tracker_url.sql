-- Список таблиц здесь перечислен поимённо и повторяет components/models.py.
-- Новые скрипты так писать не нужно: список печатает реестр —
--   python manage.py make_column_sql --tables-only
--   python manage.py make_column_sql --column "<имя>" > sql/<файл>.sql
-- Этот файл оставлен как есть: он уже применён, и трогать применённое,
-- чтобы «стало красивее», дороже, чем оставить.

-- Сужение колонки «Tracker URL» до varchar(255).
--
-- Нужен, только если колонку успели создать как varchar(1024) — первая
-- версия sql/add_tracker_url.sql делала именно так. Сейчас скрипт создаёт
-- сразу varchar(255), и на свежей базе этот файл запускать не нужно.
--
-- Запуск:  psql -d oy_system_db -f sql/shrink_tracker_url.sql
-- Другая схема:
--   psql -d oy_system_db -v schema=<схема> -f sql/shrink_tracker_url.sql
--
-- Что делает и чего не делает. Сужение типа Postgres выполняет с проверкой
-- всех строк: если хоть одна ссылка длиннее 255 символов, ALTER откажется и
-- откатит всю таблицу. Поэтому скрипт сначала считает такие строки и, если
-- они есть, таблицу пропускает и говорит об этом — молча обрезать чужие
-- данные он не станет. Длинные ссылки нужно посмотреть и решить вручную;
-- запрос для этого — в конце файла.
--
-- Таблица блокируется на время перезаписи (ACCESS EXCLUSIVE). На колонке,
-- которая почти вся пустая, это доли секунды, но лучше выполнять, когда
-- сайтом не пользуются.
--
-- Скрипт идемпотентный: где длина уже 255 или меньше, таблица пропускается.

\if :{?schema}
\else
  \set schema public
\endif

SET client_encoding = 'UTF8';
-- схема задаётся здесь, а внутри блока читается current_schema():
-- psql не подставляет переменные внутри строк в долларовых кавычках
SET search_path TO :schema;

DO $$
DECLARE
    target  text := current_schema();
    -- тот же список, что в sql/add_tracker_url.sql и components/models.py
    tables  text[] := ARRAY[
        'CAPACITOR', 'CLOCK', 'CONNECTOR', 'DIODE', 'FUSE', 'IC',
        'INDICATOR', 'INDUCTOR', 'MECHANICAL', 'PCB', 'POWER_IC',
        'RESISTOR', 'SWITCH', 'TRANSISTOR',
        'z_CAPACITOR', 'z_CLOCK', 'z_CONNECTOR', 'z_DIODE', 'z_FUSE',
        'z_IC', 'z_INDICATOR', 'z_INDUCTOR', 'z_MECHANICAL', 'z_POWER_IC',
        'z_RESISTOR', 'z_SWITCH', 'z_TRANSISTOR'
    ];
    name       text;
    relation   regclass;
    width      int;
    too_long   bigint;
    changed    int := 0;
    skipped    int := 0;
    blocked    int := 0;
    missing    int := 0;
BEGIN
    FOREACH name IN ARRAY tables LOOP
        relation := to_regclass(format('%I.%I', target, name));

        IF relation IS NULL THEN
            RAISE NOTICE 'таблицы %.% нет — пропускаю', target, name;
            missing := missing + 1;
            CONTINUE;
        END IF;

        -- atttypmod для varchar — длина плюс четыре байта заголовка
        SELECT a.atttypmod - 4 INTO width
        FROM pg_attribute a
        WHERE a.attrelid = relation
          AND a.attname = 'Tracker URL'
          AND a.attnum > 0 AND NOT a.attisdropped;

        IF width IS NULL THEN
            RAISE NOTICE '% — колонки «Tracker URL» нет, сначала '
                         'sql/add_tracker_url.sql', name;
            missing := missing + 1;
            CONTINUE;
        END IF;

        IF width <= 255 THEN
            skipped := skipped + 1;
            CONTINUE;
        END IF;

        EXECUTE format(
            'SELECT count(*) FROM %I.%I WHERE length(%I) > 255',
            target, name, 'Tracker URL') INTO too_long;

        IF too_long > 0 THEN
            RAISE WARNING '% — % ссылок длиннее 255 символов, таблицу '
                          'пропускаю: сузить тип нельзя, не обрезав их',
                          name, too_long;
            blocked := blocked + 1;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN %I TYPE varchar(255)',
                       target, name, 'Tracker URL');
        RAISE NOTICE '% — сужено с varchar(%) до varchar(255)', name, width;
        changed := changed + 1;
    END LOOP;

    RAISE NOTICE 'сужено: %, уже было 255: %, пропущено из-за длинных '
                 'ссылок: %, таблиц не найдено: %',
                 changed, skipped, blocked, missing;
END $$;

-- Проверка результата: во всех 27 строках должно быть 255.
-- SELECT table_name, character_maximum_length
-- FROM information_schema.columns
-- WHERE column_name = 'Tracker URL' ORDER BY table_name;

-- Если какие-то таблицы пропущены из-за длинных ссылок — посмотреть их
-- можно так (подставьте имя таблицы):
-- SELECT id, "Vendor PN", length("Tracker URL") AS len, "Tracker URL"
-- FROM public."RESISTOR"
-- WHERE length("Tracker URL") > 255 ORDER BY len DESC;
