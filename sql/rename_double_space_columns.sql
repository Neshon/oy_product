-- Список таблиц здесь перечислен поимённо и повторяет components/models.py.
-- Новые скрипты так писать не нужно: список печатает реестр —
--   python manage.py make_column_sql --tables-only
--   python manage.py make_column_sql --column "<имя>" > sql/<файл>.sql
-- Этот файл оставлен как есть: он уже применён, и трогать применённое,
-- чтобы «стало красивее», дороже, чем оставить.

-- Приводит имена четырёх колонок к единому виду во всех таблицах
-- компонентов. В исходной схеме их пробелы и пунктуация не совпадают
-- от таблицы к таблице:
--
--   Dimensions,  mm   / Dimensions, mm      (два пробела / один)
--   Height,  mm       / Height, mm          (два пробела / один)
--   Temperature min,°C / Temperature min, °C (без пробела перед °C / с пробелом)
--   Temperature max,°C / Temperature max, °C
--
-- Остальные однотипные колонки (Voltage, V / Value, A / Rated current, A
-- и так далее) везде оформлены как «Название, единица» — запятая и один
-- пробел, единица без пробела перед ней. К этому стилю и приводим все
-- четыре колонки.
--
-- Скрипт идемпотентный: у каждой таблицы переименовывается тот вариант
-- имени, который в ней есть, и только если целевое имя ещё не занято.
-- Повторный запуск ничего не сломает — просто не найдёт, что переименовывать.
--
-- ПРО СИМВОЛ °: колонки Temperature ищутся не точным совпадением строки,
-- а шаблоном (после запятой — необязательный пробел, ровно один любой
-- символ, затем C). Это специально: psql на Windows нередко передаёт
-- многобайтовый ° не в той кодировке, из-за чего точное сравнение строк
-- молча не совпадает и колонка тихо пропускается — без единой ошибки в
-- выводе. Строка `SET client_encoding` ниже устраняет причину, а шаблон
-- вместо точного совпадения защищает и на случай, если у кого-то ° уже
-- сохранён другим кодом символа.
--
-- ВАЖНО: после запуска обязательно обновите db_column и verbose_name в
-- components/models.py на канонические имена (см. компаньон-правку) —
-- иначе Django продолжит ждать старое имя колонки и упадёт с
-- «column does not exist».
--
-- Запуск:  psql -d oy_system_db -f sql/rename_double_space_columns.sql
-- Другая схема:
--   psql -d oy_system_db -v schema=<схема> -f sql/rename_double_space_columns.sql
--
-- Если после запуска колонки Temperature всё ещё не переименовались —
-- смотрите раздел «Если Temperature не переименовалась» в конце файла.

\if :{?schema}
\else
  \set schema public
\endif

-- Многобайтовые символы (° в Temperature) должны уйти на сервер как
-- UTF-8 независимо от кодовой страницы консоли — это и есть типичная
-- причина, по которой переименование этих двух колонок не срабатывает
-- на Windows, хотя ASCII-колонки (Dimensions, Height) проходят нормально.
SET client_encoding = 'UTF8';
SET search_path TO :schema;

DO $$
DECLARE
    tbl text;
    old_name text;
    new_name text;
    -- точные пары "старое имя -> новое" — для Dimensions и Height:
    -- в них только ASCII, кодировка их не портит, точное совпадение надёжно
    exact_renames text[][] := ARRAY[
        ARRAY['Dimensions,  mm', 'Dimensions, mm'],
        ARRAY['Height,  mm',     'Height, mm']
    ];
    pair text[];
    found_col text;
    tables text[] := ARRAY[
        'CAPACITOR', 'CLOCK', 'CONNECTOR', 'DIODE', 'FUSE', 'IC',
        'INDICATOR', 'INDUCTOR', 'MECHANICAL', 'PCB', 'POWER_IC',
        'RESISTOR', 'SWITCH', 'TRANSISTOR',
        'z_CAPACITOR', 'z_CLOCK', 'z_CONNECTOR', 'z_DIODE', 'z_FUSE', 'z_IC',
        'z_INDICATOR', 'z_INDUCTOR', 'z_MECHANICAL', 'z_POWER_IC',
        'z_RESISTOR', 'z_SWITCH', 'z_TRANSISTOR'
    ];
    renamed_count int := 0;
BEGIN
    FOREACH tbl IN ARRAY tables LOOP
        IF to_regclass(format('%I.%I', current_schema(), tbl)) IS NULL THEN
            RAISE NOTICE 'таблицы % нет в схеме % — пропускаю', tbl, current_schema();
            CONTINUE;
        END IF;

        -- Dimensions, Height: точное совпадение
        FOREACH pair SLICE 1 IN ARRAY exact_renames LOOP
            old_name := pair[1];
            new_name := pair[2];
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = tbl AND column_name = old_name
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = tbl AND column_name = new_name
            ) THEN
                EXECUTE format('ALTER TABLE %I RENAME COLUMN %I TO %I',
                               tbl, old_name, new_name);
                RAISE NOTICE '% : "%" -> "%"', tbl, old_name, new_name;
                renamed_count := renamed_count + 1;
            END IF;
        END LOOP;

        -- Temperature min/max: по шаблону, символ ° не сравнивается напрямую
        FOR found_col IN
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = tbl
              AND (column_name ~ '^Temperature min,\s*.C$'
                   OR column_name ~ '^Temperature max,\s*.C$')
        LOOP
            new_name := CASE
                WHEN found_col ~ '^Temperature min' THEN 'Temperature min, °C'
                ELSE 'Temperature max, °C'
            END;
            IF found_col = new_name THEN
                CONTINUE; -- уже канонично
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = tbl AND column_name = new_name
            ) THEN
                RAISE NOTICE '% : "%" — целевое имя уже занято, пропускаю',
                            tbl, found_col;
                CONTINUE;
            END IF;
            EXECUTE format('ALTER TABLE %I RENAME COLUMN %I TO %I',
                           tbl, found_col, new_name);
            RAISE NOTICE '% : "%" -> "%"', tbl, found_col, new_name;
            renamed_count := renamed_count + 1;
        END LOOP;
    END LOOP;

    RAISE NOTICE 'Переименовано колонок: %', renamed_count;
END $$;

-- Диагностика: что в итоге осталось в таблицах по колонкам Temperature.
-- Если тут видно что-то, кроме "Temperature min, °C" / "Temperature max, °C",
-- значит рядом с этими таблицами есть третий вариант написания, которого
-- скрипт не ждал, — пришлите этот вывод, разберём.
SELECT table_name AS "Таблица", column_name AS "Колонка (как сейчас)"
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND column_name LIKE 'Temperature%'
ORDER BY table_name, column_name;

-- ============================================================================
-- Если Temperature не переименовалась
-- ============================================================================
-- 1. Проверьте кодировку соединения ДО запуска скрипта:
--
--      SHOW client_encoding;
--
--    Если это не UTF8 — до строки `SET client_encoding = 'UTF8';` дело
--    может не доходить из-за того, как сама консоль передаёт файл psql.
--    На Windows-консоли (cmd) часто помогает переключить кодовую страницu
--    перед запуском:
--
--      chcp 65001
--      psql -d oy_system_db -f sql/rename_double_space_columns.sql
--
--    Или явно указать кодировку клиента переменной окружения:
--
--      set PGCLIENTENCODING=UTF8
--      psql -d oy_system_db -f sql/rename_double_space_columns.sql
--
-- 2. Если и это не помогло — выполните SELECT из диагностического блока
--    выше отдельно и посмотрите, что реально хранится в column_name.
--    Самый надёжный способ увидеть точные байты — через pgAdmin или
--    DBeaver (там кодировка консоли ни при чём), либо этим запросом,
--    который покажет реальный код каждого символа после запятой:
--
--      SELECT table_name, column_name,
--             (SELECT string_agg(to_hex(ascii(c)), ' ')
--              FROM unnest(string_to_array(column_name, NULL)) AS c) AS codes
--      FROM information_schema.columns
--      WHERE table_schema = current_schema()
--        AND column_name LIKE 'Temperature%';
--
--    Пришлите этот вывод — если там окажется третий вариант символа
--    (не U+00B0, обычный градус), шаблон в скрипте нужно будет расширить.
