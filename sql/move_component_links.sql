-- Список таблиц здесь перечислен поимённо и повторяет components/models.py.
-- Новые скрипты так писать не нужно: список печатает реестр —
--   python manage.py make_column_sql --tables-only
--   python manage.py make_column_sql --column "<имя>" > sql/<файл>.sql
-- Этот файл оставлен как есть: он уже применён, и трогать применённое,
-- чтобы «стало красивее», дороже, чем оставить.

-- Перенос ссылок из oy_component_link в колонку «Tracker URL».
--
-- Запускается ПОСЛЕ sql/add_tracker_url.sql и ДО `manage.py migrate`:
-- миграция удаляет таблицу oy_component_link вместе с данными, и переносить
-- будет уже нечего.
--
-- Запуск:  psql -d oy_system_db -f sql/move_component_links.sql
-- Другие схемы:
--   psql -d oy_system_db -v schema=<таблицы компонентов> \
--        -v app_schema=<схема Django> -f sql/move_component_links.sql
--
-- Что важно знать до запуска. В старой таблице у компонента могло быть
-- несколько ссылок — уникальной была пара «компонент + адрес», а не сам
-- компонент. В колонку помещается одна. Берётся самая ранняя: она с
-- наибольшей вероятностью та, ради которой компонент и заводили, а
-- добавленные позже — уточнения. Остальные скрипт не удаляет молча, а
-- выписывает в NOTICE перед переносом: если их много, посмотрите список
-- до того, как миграция уберёт таблицу.
--
-- Уже заполненные вручную значения не перезаписываются.
--
-- Скрипт идемпотентный: повторный запуск ничего не изменит.

\if :{?schema}
\else
  \set schema public
\endif

\if :{?app_schema}
\else
  \set app_schema oy_system
\endif

SET client_encoding = 'UTF8';
-- Схемы передаются в блок через настройки сеанса, а не подстановкой: psql
-- не заменяет переменные внутри строк в долларовых кавычках, и :'schema'
-- ушло бы на сервер как есть — «ошибка синтаксиса около ":"».
SET search_path TO :schema;
SELECT set_config('oy.app_schema', :'app_schema', false);

DO $$
DECLARE
    data_schema text := current_schema();
    links       text := format('%I.%I', current_setting('oy.app_schema'),
                               'oy_component_link');
    -- тот же список, что в sql/add_tracker_url.sql и в components/models.py
    tables      text[] := ARRAY[
        'CAPACITOR', 'CLOCK', 'CONNECTOR', 'DIODE', 'FUSE', 'IC',
        'INDICATOR', 'INDUCTOR', 'MECHANICAL', 'PCB', 'POWER_IC',
        'RESISTOR', 'SWITCH', 'TRANSISTOR',
        'z_CAPACITOR', 'z_CLOCK', 'z_CONNECTOR', 'z_DIODE', 'z_FUSE',
        'z_IC', 'z_INDICATOR', 'z_INDUCTOR', 'z_MECHANICAL', 'z_POWER_IC',
        'z_RESISTOR', 'z_SWITCH', 'z_TRANSISTOR'
    ];
    name        text;
    relation    regclass;
    extra       record;
    moved       int := 0;
    total       int := 0;
BEGIN
    IF to_regclass(links) IS NULL THEN
        RAISE NOTICE 'таблицы % нет — переносить нечего', links;
        RETURN;
    END IF;

    -- сначала показываем компоненты, у которых ссылок больше одной:
    -- в колонку попадёт только самая ранняя
    FOR extra IN EXECUTE format($q$
        SELECT component_table, component_id, count(*) AS n
        FROM %s GROUP BY 1, 2 HAVING count(*) > 1 ORDER BY 3 DESC, 1, 2
    $q$, links)
    LOOP
        RAISE NOTICE 'у % #% ссылок: % — перенесём самую раннюю',
            extra.component_table, extra.component_id, extra.n;
    END LOOP;

    FOREACH name IN ARRAY tables LOOP
        relation := to_regclass(format('%I.%I', data_schema, name));

        IF relation IS NULL THEN
            RAISE NOTICE 'таблицы %.% нет — пропускаю', data_schema, name;
            CONTINUE;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM pg_attribute a
            WHERE a.attrelid = relation AND a.attname = 'Tracker URL'
              AND a.attnum > 0 AND NOT a.attisdropped)
        THEN
            RAISE NOTICE '% — нет колонки «Tracker URL», сначала '
                         'sql/add_tracker_url.sql', name;
            CONTINUE;
        END IF;

        EXECUTE format($q$
            UPDATE %I.%I AS target
            SET %I = source.url
            FROM (
                SELECT DISTINCT ON (component_id) component_id, url
                FROM %s
                WHERE component_table = %L
                ORDER BY component_id, created, id
            ) AS source
            WHERE target.id = source.component_id
              -- заполненное вручную не трогаем
              AND (target.%I IS NULL OR btrim(target.%I) IN ('', '---', '-', '?'))
        $q$, data_schema, name, 'Tracker URL', links, name,
             'Tracker URL', 'Tracker URL');

        GET DIAGNOSTICS moved = ROW_COUNT;
        IF moved > 0 THEN
            RAISE NOTICE '% — перенесено ссылок: %', name, moved;
            total := total + moved;
        END IF;
    END LOOP;

    RAISE NOTICE 'всего перенесено: %', total;
END $$;

-- Проверка результата:
-- SELECT count(*) FROM public."RESISTOR" WHERE "Tracker URL" IS NOT NULL;
