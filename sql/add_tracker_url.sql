-- Список таблиц здесь перечислен поимённо и повторяет components/models.py.
-- Новые скрипты так писать не нужно: список печатает реестр —
--   python manage.py make_column_sql --tables-only
--   python manage.py make_column_sql --column "<имя>" > sql/<файл>.sql
-- Этот файл оставлен как есть: он уже применён, и трогать применённое,
-- чтобы «стало красивее», дороже, чем оставить.

-- Колонка «Tracker URL» во все таблицы компонентов.
--
-- Раньше ссылки на задачи трекера лежали в отдельной таблице
-- oy_component_link: колонки под них в исходной схеме не было, а заводить её
-- в 27 чужих таблиц не хотелось. Практика показала, что ссылка у
-- компонента одна и ведёт себя как обычный параметр — её видно в карточке,
-- по ней ищут, её правят руками. Поэтому она переезжает в сами таблицы.
--
-- Запуск:  psql -d oy_system_db -f sql/add_tracker_url.sql
-- Другая схема:
--   psql -d oy_system_db -v schema=<схема> -f sql/add_tracker_url.sql
--
-- Порядок перехода:
--   1. копия базы:
--        pg_dump -Fc -d oy_system_db -f before_tracker_url.dump
--   2. этот скрипт — добавит колонку;
--   3. sql/move_component_links.sql — перенесёт то, что уже накоплено
--      в oy_component_link, в новую колонку;
--   4. python manage.py migrate — удалит таблицу oy_component_link;
--   5. python manage.py check_schema — сверит модели с колонками.
--
-- Шаги 2 и 3 нужно выполнить ДО миграции: она удаляет таблицу вместе с
-- данными, и переносить будет уже нечего.
--
-- Скрипт идемпотентный: где колонка уже есть, она пропускается. Таблицы
-- перечислены поимённо — тот же список, что в components/models.py; если
-- таблицы из списка в схеме нет, скрипт скажет об этом и пойдёт дальше.

\if :{?schema}
\else
  \set schema public
\endif

SET client_encoding = 'UTF8';
-- Схема задаётся через search_path, а внутри блока читается функцией
-- current_schema(). Подставить :'schema' прямо в тело DO нельзя: psql не
-- заменяет переменные внутри строк в долларовых кавычках, и двоеточие
-- уходит на сервер как есть — «ошибка синтаксиса около ":"».
SET search_path TO :schema;

DO $$
DECLARE
    target  text := current_schema();
    tables  text[] := ARRAY[
        'CAPACITOR', 'CLOCK', 'CONNECTOR', 'DIODE', 'FUSE', 'IC',
        'INDICATOR', 'INDUCTOR', 'MECHANICAL', 'PCB', 'POWER_IC',
        'RESISTOR', 'SWITCH', 'TRANSISTOR',
        'z_CAPACITOR', 'z_CLOCK', 'z_CONNECTOR', 'z_DIODE', 'z_FUSE',
        'z_IC', 'z_INDICATOR', 'z_INDUCTOR', 'z_MECHANICAL', 'z_POWER_IC',
        'z_RESISTOR', 'z_SWITCH', 'z_TRANSISTOR'
    ];
    name     text;
    relation regclass;
    added    int := 0;
    skipped  int := 0;
    missing  int := 0;
BEGIN
    FOREACH name IN ARRAY tables LOOP
        relation := to_regclass(format('%I.%I', target, name));

        IF relation IS NULL THEN
            RAISE NOTICE 'таблицы %.% нет — пропускаю', target, name;
            missing := missing + 1;
            CONTINUE;
        END IF;

        IF EXISTS (
            SELECT 1 FROM pg_attribute a
            WHERE a.attrelid = relation
              AND a.attname = 'Tracker URL'
              AND a.attnum > 0 AND NOT a.attisdropped)
        THEN
            skipped := skipped + 1;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN %I varchar(255)',
                       target, name, 'Tracker URL');
        RAISE NOTICE 'колонка добавлена в %', name;
        added := added + 1;
    END LOOP;

    RAISE NOTICE 'добавлено: %, уже было: %, таблиц не найдено: %',
        added, skipped, missing;

    IF missing > 0 THEN
        RAISE WARNING 'часть таблиц не найдена — проверьте схему (%)', target;
    END IF;
END $$;

-- Проверка результата: должно быть 27 строк.
-- SELECT table_name FROM information_schema.columns
-- WHERE column_name = 'Tracker URL' ORDER BY table_name;
