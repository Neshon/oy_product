"""Первичное наполнение справочника из уже введённых данных.

    python manage.py load_options --field smt_tht
    python manage.py load_options --field package --table RESISTOR --table z_RESISTOR

Столбец создаётся, если его ещё нет; значения собираются запросом DISTINCT
по указанным таблицам. Команда идемпотентная: повторный запуск ничего не
дублирует и не трогает то, что уже поправили руками.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from components.models import OptionField, OptionValue
from components.registry import CATEGORIES


class Command(BaseCommand):
    help = "Собирает значения столбца из таблиц компонентов в справочник"

    def add_arguments(self, parser):
        parser.add_argument("--field", action="append", dest="fields",
                            required=True,
                            help="имя поля модели; можно указать несколько раз")
        parser.add_argument("--table", action="append", dest="tables",
                            help="таблица-источник (по умолчанию все, где есть поле)")
        parser.add_argument("--limit-to-tables", action="store_true",
                            help="ограничить действие столбца этими же таблицами")

    def handle(self, *args, **options):
        wanted = set(options["tables"] or [])
        for field in options["fields"]:
            self.collect(field, wanted, options["limit_to_tables"])

    def collect(self, field, wanted, limit_to_tables):

        categories = [c for c in CATEGORIES.values()
                      if field in c.field_names
                      and (not wanted or c.table in wanted)]
        if not categories:
            raise CommandError(f"Поле «{field}» не найдено ни в одной таблице")

        # столбец ищется вместе с набором таблиц: один и тот же столбец
        # может быть заведён отдельно для разных групп
        tables = sorted(c.table for c in categories) if limit_to_tables else []
        option_field, _ = OptionField.objects.get_or_create(
            field=field, tables=tables)

        found = set()
        for category in categories:
            try:
                values = (category.model.objects
                          .exclude(**{f"{field}__isnull": True})
                          .exclude(**{field: ""})
                          # без сброса сортировки (у таблиц она по -id)
                          # ключ попадает в запрос рядом со значением, и
                          # distinct перестаёт что-либо убирать: база
                          # отдаёт все строки таблицы, а повторы снимает
                          # уже питон
                          .order_by()
                          .values_list(field, flat=True)
                          .distinct())
            except DatabaseError as exc:
                self.stderr.write(self.style.WARNING(f"{category.table}: {exc}"))
                continue
            found.update(v.strip() for v in values if v and v.strip())

        added = 0
        for value in sorted(found):
            _, is_new = OptionValue.objects.get_or_create(
                option_field=option_field, value=value)
            added += int(is_new)

        self.stdout.write(self.style.SUCCESS(
            f"Столбец «{field}»: значений всего {option_field.values.count()}, "
            f"добавлено {added}. Таблиц-источников: {len(categories)}."))
