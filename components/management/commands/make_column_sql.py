"""Генерирует SQL для правки всех таблиц компонентов сразу.

Зачем. Колонок в исходной схеме Django не создаёт, поэтому такие правки
делаются скриптами из ``sql/``. Каждый такой скрипт перечислял 27 таблиц
поимённо — тот же список, что в ``components/models.py``. Два списка рано
или поздно расходятся: добавили группу, про SQL забыли, и колонка не
появилась ровно в той таблице, ради которой всё затевалось.

Теперь список один — реестр категорий, — а скрипт по нему печатается:

    python manage.py make_column_sql --column "Tracker URL" \\
        > sql/add_tracker_url.sql

Посмотреть только список таблиц (например, чтобы вставить в свой запрос):

    python manage.py make_column_sql --tables-only

Сам получившийся скрипт идемпотентен: где колонка уже есть — пропускает,
какой таблицы в схеме нет — говорит об этом и идёт дальше, а в конце
предупреждает, сколько не нашлось. Молча пропустить таблицу он не может:
это и есть тот случай, ради которого всё делается.
"""

from django.core.management.base import BaseCommand, CommandError

from components.registry import CATEGORIES

# По сколько имён таблиц в строке — чтобы сгенерированное читалось глазами
PER_LINE = 6

HEADER = """\
-- Колонка «{column}» во все таблицы компонентов ({count} шт.).
--
-- ФАЙЛ СГЕНЕРИРОВАН. Не правьте список таблиц руками — он приедет из
-- реестра при следующем запуске:
--   python manage.py make_column_sql --column "{column}" --type "{type}"
--
-- Запуск:       psql -d oy_system_db -f {filename}
-- Другая схема: psql -d oy_system_db -v schema=<схема> -f {filename}
--
-- Перед запуском снимите копию:
--   pg_dump -Fc -d oy_system_db -f before_{slug}.dump
-- После — сверьте модели со схемой:
--   python manage.py check_schema

\\if :{{?schema}}
\\else
  \\set schema public
\\endif

SET client_encoding = 'UTF8';
-- Схема задаётся через search_path, а внутри блока читается функцией
-- current_schema(). Подставить :'schema' прямо в тело DO нельзя: psql не
-- заменяет переменные внутри строк в долларовых кавычках, и двоеточие
-- уходит на сервер как есть — «ошибка синтаксиса около ":"».
SET search_path TO :schema;
"""

BODY = """
DO $$
DECLARE
    target  text := current_schema();
    tables  text[] := ARRAY[
{tables}
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
              AND a.attname = '{column}'
              AND a.attnum > 0 AND NOT a.attisdropped)
        THEN
            skipped := skipped + 1;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN %I {type}',
                       target, name, '{column}');
        RAISE NOTICE 'колонка добавлена в %', name;
        added := added + 1;
    END LOOP;

    RAISE NOTICE 'добавлено: %, уже было: %, таблиц не найдено: %',
        added, skipped, missing;

    IF missing > 0 THEN
        RAISE WARNING 'часть таблиц не найдена — проверьте схему (%)', target;
    END IF;
END $$;

-- Проверка результата: должно быть {count} строк.
-- SELECT table_name FROM information_schema.columns
-- WHERE column_name = '{column}' ORDER BY table_name;
"""


def component_tables():
    """Имена таблиц компонентов: сначала рабочие, потом замены.

    Порядок тот же, в каком категории объявлены в реестре, — чтобы
    сгенерированный файл не менялся от запуска к запуску без причины.
    """
    main = [c.table for c in CATEGORIES.values() if not c.replacement]
    replacements = [c.table for c in CATEGORIES.values() if c.replacement]
    return main + replacements


def _array_literal(tables, indent=" " * 8):
    """Имена в кавычках, по :data:`PER_LINE` в строке."""
    lines = []
    for start in range(0, len(tables), PER_LINE):
        chunk = tables[start:start + PER_LINE]
        lines.append(indent + ", ".join(f"'{name}'" for name in chunk))
    return ",\n".join(lines)


class Command(BaseCommand):
    help = "Печатает SQL, добавляющий колонку во все таблицы компонентов"

    def add_arguments(self, parser):
        parser.add_argument(
            "--column",
            help="имя колонки как оно будет в базе, например «Tracker URL»")
        parser.add_argument(
            "--type", default="varchar(255)",
            help="тип колонки (по умолчанию varchar(255) — как у остальных)")
        parser.add_argument(
            "--filename", default="sql/add_column.sql",
            help="как файл будет называться: подставляется в подсказки внутри")
        parser.add_argument(
            "--tables-only", action="store_true",
            help="напечатать только список таблиц, без скрипта")

    def handle(self, *args, **options):
        tables = component_tables()

        if options["tables_only"]:
            for name in tables:
                self.stdout.write(name)
            return

        column = options["column"]
        if not column:
            raise CommandError(
                "укажите --column (или --tables-only, если нужен только "
                "список таблиц)")
        if '"' in column or "'" in column:
            # имя уходит внутрь строкового литерала SQL, а кавычек в именах
            # колонок этой схемы не бывает — проще отказать, чем экранировать
            raise CommandError("в имени колонки не должно быть кавычек")

        slug = column.lower().replace(" ", "_").replace("/", "_")
        context = {
            "column": column,
            "type": options["type"],
            "count": len(tables),
            "filename": options["filename"],
            "slug": slug,
        }
        self.stdout.write(HEADER.format(**context))
        self.stdout.write(BODY.format(tables=_array_literal(tables),
                                      **context))
