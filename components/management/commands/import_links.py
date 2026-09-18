"""Импорт внешних ссылок на компоненты из CSV.

Файл — выгрузка задач трекера с двумя колонками:

    Ключ,Задача
    https://tracker.yandex.ru/OYLIB-359,Создание микросхемы питания LM5066IPMHE/NOPB

«Ключ» — ссылка, «Задача» — название, в конце которого стоит артикул.
Компонент ищется по артикулу в самой библиотеке (см. components.links),
а не угадывается из формата строки.

    python manage.py import_links links.csv --dry-run   # посмотреть, не записывая
    python manage.py import_links links.csv
    python manage.py import_links links.csv --unmatched не_нашлись.csv
"""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from components.links import (TITLE_COLUMN, URL_COLUMN, LinkFileError,
                              build_index, read_rows, resolve_rows, save_links)

# сколько примеров ненайденного показывать в отчёте
EXAMPLES = 15


class Command(BaseCommand):
    help = "Импортирует ссылки из CSV и сопоставляет их с компонентами"

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?",
                            help="CSV с колонками «Ключ» и «Задача»")
        parser.add_argument("--dry-run", action="store_true",
                            help="показать результат сопоставления, не записывая")
        parser.add_argument("--source", default="",
                            help="пометка источника; по умолчанию имя файла")
        parser.add_argument("--unmatched", default="",
                            help="куда выписать строки, для которых компонент "
                                 "не нашёлся")

    def handle(self, *args, **options):
        if not options["path"]:
            raise CommandError("Укажите путь к CSV")

        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")

        try:
            rows = read_rows(path)
        except LinkFileError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"Строк в файле: {len(rows)}. Строю индекс артикулов…")
        index = build_index()
        if not index[0] and not index[1]:
            raise CommandError("В библиотеке не нашлось ни одного артикула — "
                              "проверьте подключение к базе")

        source = options["source"] or path.stem
        matched, unmatched, already = resolve_rows(rows, index)

        self._report(matched, unmatched, already)
        if options["unmatched"]:
            self._write_unmatched(Path(options["unmatched"]), unmatched)

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(
                "Пробный проход — в базу ничего не записано."))
            return

        filled, replaced = save_links(matched, source)
        self.stdout.write(self.style.SUCCESS(
            f"Ссылок проставлено: {filled}."))
        if replaced:
            # колонка одна: новая ссылка вытесняет прежнюю, и об этом
            # нужно сказать вслух — вдруг ту заводили руками
            self.stdout.write(self.style.WARNING(
                f"Заменено ранее стоявших ссылок: {replaced}."))

    def _report(self, matched, unmatched, already=()):
        total = len(matched) + len(unmatched) + len(already)
        links = sum(len(item["targets"]) for item in matched)
        self.stdout.write(
            f"Сопоставлено задач: {len(matched)} из {total}; "
            f"ссылок к записи: {links}.")
        if already:
            # при повторной загрузке файла это обычно большинство строк
            self.stdout.write(f"Уже заведено раньше, пропускаю: {len(already)}")

        # одна задача может указывать на несколько записей — например, на
        # компонент и его аналог с тем же артикулом. Это не ошибка, но
        # знать об этом полезно
        many = [item for item in matched if len(item["targets"]) > 1]
        if many:
            self.stdout.write(f"Задач, попавших сразу в несколько записей: "
                              f"{len(many)}")
            for item in many[:EXAMPLES]:
                where = ", ".join(table for table, _ in item["targets"])
                self.stdout.write(f"  {item['pn']} → {where}")

        if unmatched:
            self.stdout.write(self.style.WARNING(
                f"Не нашлось компонента: {len(unmatched)}"))
            for row in unmatched[:EXAMPLES]:
                self.stdout.write(f"  {row['title']}")
                # похожие артикулы: чаще всего это та же деталь,
                # записанная с лишним суффиксом или другими разделителями
                for hint in row.get("hints", []):
                    self.stdout.write(
                        f"      возможно: {hint['pn']} ({hint['reason']})")
            if len(unmatched) > EXAMPLES:
                self.stdout.write(f"  …и ещё {len(unmatched) - EXAMPLES}")

    def _write_unmatched(self, path, unmatched):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow([URL_COLUMN, TITLE_COLUMN, "Возможно, это"])
            for row in unmatched:
                hints = "; ".join(hint["pn"] for hint in row.get("hints", []))
                writer.writerow([row["url"], row["title"], hints])
        self.stdout.write(f"Ненайденное выписано в {path}")
