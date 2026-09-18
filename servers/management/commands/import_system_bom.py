"""Импорт System BOM из командной строки.

То же, что и загрузка через сайт, но пригодно для пачки файлов и для
разбора без записи:

    python manage.py import_system_bom HN203I-1MPF-02.xlsx --dry-run
    python manage.py import_system_bom ./boms
    python manage.py import_system_bom *.xlsx

Принимает и каталог, и шаблон, и отдельные файлы: шаблон раскрывается самой
командой, потому что в cmd и PowerShell оболочка этого не делает.
"""

import glob
import pathlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from servers.importer import ImportError_, apply_rows, read


def expand(paths, *suffixes):
    """Каталоги и шаблоны -> список файлов, без повторов и по порядку."""
    found = []
    for path in paths:
        item = pathlib.Path(path)
        if item.is_dir():
            found += [child for child in sorted(item.rglob("*"))
                      if child.suffix.lower() in suffixes]
        elif any(sign in path for sign in "*?["):
            found += sorted(pathlib.Path(name) for name in glob.glob(path))
        else:
            found.append(item)

    unique = {item.resolve(): item for item in found if item.is_file()}
    return [unique[key] for key in sorted(unique)]


class Command(BaseCommand):
    help = "Загружает состав изделия из файла System BOM"

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+",
                            help="файлы .xlsx, каталог с ними или шаблон")
        parser.add_argument("--dry-run", action="store_true",
                            help="только разобрать и показать, что вышло")
        parser.add_argument("--keep", action="store_true",
                            help="не удалять строки прежнего импорта")

    def handle(self, *args, **options):
        files = expand(options["paths"], ".xlsx", ".xlsm")
        if not files:
            raise CommandError("Не нашёл ни одного файла .xlsx по этим путям.")

        for path in files:
            try:
                header, rows = read(path)
            except ImportError_ as exc:
                raise CommandError(f"{path}: {exc}") from exc

            self.stdout.write(f"\n{path}: изделие {header['oy_pn']}, "
                              f"строк {len(rows)}")
            if options["dry_run"]:
                for row in rows[:200]:
                    self.stdout.write(
                        f"   {row['section']:<10} {row['kind']} "
                        f"{row['oy_pn'] or row['gct_pn']:<32} "
                        f"{row['quantity']} {row['unit']}")
                continue

            with transaction.atomic():
                # в источнике храним имя файла, а не полный путь: пути на
                # разных машинах разные, а различает файлы имя
                report = apply_rows(header, rows, source=path.name,
                                    replace=not options["keep"])
            self.stdout.write(self.style.SUCCESS(
                f"   строк состава: {report['lines']}, "
                f"новых позиций: {len(report['items_created'])}"))
            for row, why in report["skipped"]:
                self.stdout.write(self.style.WARNING(f"   строка {row}: {why}"))
