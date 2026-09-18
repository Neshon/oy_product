"""Приведение обозначений позиций в уже загруженных составах.

Новые загрузки приводятся сами — и импорт, и ручной ввод пропускают
Part References через ``boards.references``. Строки, загруженные до этого,
остались как были: где-то через пробел, где-то через точку с запятой.
Команда проходит по ним один раз.

    python manage.py normalize_references --dry-run   # только посмотреть
    python manage.py normalize_references
    python manage.py normalize_references --board HSBP-5S01-02C
"""

from django.core.management.base import BaseCommand

from boards.models import BoardItem
from boards.references import normalize_references

BATCH = 500
EXAMPLES = 15


class Command(BaseCommand):
    help = "Приводит Part References в составах плат к записи через запятую"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="показать, что изменилось бы, и ничего не писать")
        parser.add_argument("--board", action="append", dest="boards",
                            help="ограничиться платой с этим OY P/N")

    def handle(self, *args, **options):
        items = BoardItem.objects.exclude(references="")
        if options["boards"]:
            items = items.filter(revision__board__base_pn__in=options["boards"])

        total = items.count()
        if not total:
            self.stdout.write("Обозначения нигде не заполнены — нечего приводить.")
            return

        dry_run = options["dry_run"]
        self.stdout.write(f"Строк с обозначениями: {total}."
                          + (" Пробный проход, записи не будет." if dry_run else ""))

        changed, shown = 0, 0
        batch = []
        # строки читаются потоком и пишутся пачками: в больших базах их
        # сотни тысяч, и собирать все изменения в один список нельзя
        for item in items.iterator(chunk_size=BATCH):
            fixed = normalize_references(item.references)
            if fixed == item.references:
                continue
            changed += 1
            if shown < EXAMPLES:
                shown += 1
                self.stdout.write(f"  {item.references!r} → {fixed!r}")
            if dry_run:
                continue
            item.references = fixed
            batch.append(item)
            if len(batch) >= BATCH:
                BoardItem.objects.bulk_update(batch, ["references"])
                batch.clear()

        if batch:
            BoardItem.objects.bulk_update(batch, ["references"])

        if changed > shown:
            self.stdout.write(f"  …и ещё {changed - shown}")

        if not changed:
            self.stdout.write(self.style.SUCCESS("Всё уже приведено к запятым."))
        elif dry_run:
            self.stdout.write(self.style.WARNING(
                f"Изменилось бы строк: {changed}. Запись не выполнялась."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Приведено строк: {changed}."))
