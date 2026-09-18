"""Перенос позиций и составов изделий из выгрузки Confluence.

    python tools/confluence_parse.py ./confluence -o confluence.json
    python manage.py import_confluence confluence.json

**Карточки плат и ревизий эта команда больше не заводит.** Раньше их
писал ``boards.confluence`` из того же JSON — то есть те же страницы
разбирались дважды, разными разборщиками, с двумя копиями карты полей.
Копии успели разойтись: в одной было поле «Маршрут инструкций», в другой —
тип платы по наименованию, и что именно попадёт в базу, зависело от того,
какой командой запустили импорт.

Остался один путь, прямо из markdown:

    python manage.py import_cards ./pages

Порядок при первой заливке имеет значение:

    python manage.py import_cards ./pages          # 1. платы и ревизии
    python manage.py import_confluence confluence.json   # 2. изделия

Позиция-двойник платы ищет её по номеру, и если платы ещё нет, заведётся
обычная позиция без связи с реестром. Наоборот — платы без позиций —
чинится командой ``sync_boards``.
"""

import json

from django.core.management.base import BaseCommand
from django.db import transaction

from servers.confluence import Loader as ItemLoader


class Command(BaseCommand):
    help = "Загружает позиции и состав изделий из разобранного экспорта Confluence"

    def add_arguments(self, parser):
        parser.add_argument("path", help="файл JSON")
        parser.add_argument("--keep", action="store_true",
                            help="не удалять строки прежнего импорта")

    def handle(self, *args, **options):
        with open(options["path"], encoding="utf-8") as handle:
            data = json.load(handle)

        with transaction.atomic():
            items = ItemLoader().load(data, replace=not options["keep"])

        self.stdout.write(self.style.SUCCESS(
            f"позиции: заведено {len(items['created'])}, "
            f"обновлено {len(items['updated'])}, "
            f"строк состава {items['lines']}"))
        for number, why in items["skipped"]:
            self.stdout.write(self.style.WARNING(f"   {number}: {why}"))

        self.stdout.write(
            "карточки плат и ревизий заводит import_cards — "
            "если их ещё не грузили, позиции-платы остались без связи "
            "с реестром")
