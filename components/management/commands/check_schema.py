"""Сверяет модели с тем, что действительно лежит в PostgreSQL.

Модели неуправляемые, поэтому расхождение схемы обнаруживается только
в момент запроса. Команда находит его заранее:

    python manage.py check_schema
"""

from django.core.management.base import BaseCommand
from django.db import connection

from components.registry import CATEGORIES


class Command(BaseCommand):
    help = "Проверяет, что таблицы и колонки библиотеки совпадают с моделями"

    def add_arguments(self, parser):
        parser.add_argument("--counts", action="store_true",
                            help="дополнительно показать число строк")

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # search_path может содержать несколько схем: служебные таблицы
            # Django и таблицы компонентов допустимо держать раздельно
            cursor.execute("SELECT current_schemas(false)")
            search_path = cursor.fetchone()[0] or []
            priority = {name: index for index, name in enumerate(search_path)}

            # current_schemas() молча выбрасывает из пути схемы, которых в
            # базе нет, — а это самая частая причина «нет таблицы»: схему
            # переименовали, а POSTGRES_SCHEMA остался прежним. Поэтому
            # сверяем, что задано, с тем, что нашлось
            cursor.execute("SHOW search_path")
            wanted = [part.strip().strip('"')
                      for part in (cursor.fetchone()[0] or "").split(",")]
            unknown = [name for name in wanted
                       if name and name != "$user" and name not in search_path]

            # где таблицы лежат на самом деле — чтобы не гадать, если их
            # нет в пути поиска
            cursor.execute("""
                SELECT table_name, table_schema
                FROM information_schema.tables
                WHERE table_name = ANY (%s)
            """, [[category.table for category in CATEGORIES.values()]])
            elsewhere = {}
            for table, schema in cursor.fetchall():
                elsewhere.setdefault(table, []).append(schema)

            cursor.execute("""
                SELECT table_schema, table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = ANY (current_schemas(false))
            """)
            actual, schema_of = {}, {}
            for schema, table, column in cursor.fetchall():
                # при совпадении имён побеждает схема, которая раньше в пути
                known = schema_of.get(table)
                if known is not None and priority[known] < priority[schema]:
                    continue
                if known != schema:
                    schema_of[table] = schema
                    actual[table] = set()
                actual[table].add(column)

        self.stdout.write("Схемы в поиске: "
                          + (", ".join(search_path) or "пусто — проверьте "
                             "POSTGRES_SCHEMA"))
        if unknown:
            self.stderr.write(self.style.ERROR(
                "В POSTGRES_SCHEMA указаны схемы, которых в базе нет: "
                + ", ".join(unknown)
                + ". PostgreSQL молча их игнорирует — таблицы из них "
                  "найдены не будут."))

        problems = 0
        for category in CATEGORIES.values():
            table = category.table
            if table not in actual:
                found = ", ".join(sorted(elsewhere.get(table, [])))
                hint = (f" — она есть в схеме {found}, добавьте её "
                        f"в POSTGRES_SCHEMA" if found else "")
                self.stderr.write(self.style.ERROR(
                    f"нет таблицы {table}{hint}"))
                problems += 1
                continue

            expected = {f.column for f in category.model._meta.fields}
            missing = expected - actual[table]
            extra = actual[table] - expected

            if missing:
                problems += 1
                self.stderr.write(self.style.ERROR(
                    f"{table}: модель ждёт колонки, которых нет в БД — "
                    + ", ".join(sorted(missing))))
            if extra:
                self.stdout.write(self.style.WARNING(
                    f"{table}: в БД есть колонки вне модели — "
                    + ", ".join(sorted(extra))))
            if not missing and not extra:
                line = (f"{schema_of[table]}.{table}: совпадает "
                        f"({len(expected)} колонок)")
                if options["counts"]:
                    line += f", строк: {category.model.objects.count()}"
                self.stdout.write(self.style.SUCCESS(line))

        if problems:
            # таблиц нет вовсе — дело почти всегда в пути поиска, а не
            # в моделях; советовать править models.py тут вредно
            lost = all(category.table not in actual
                       for category in CATEGORIES.values())
            self.stderr.write(self.style.ERROR(
                f"\nРасхождений: {problems}. "
                + ("Проверьте POSTGRES_SCHEMA в .env." if lost
                   else "Поправьте components/models.py.")))
        else:
            self.stdout.write(self.style.SUCCESS("\nСхема и модели согласованы."))
