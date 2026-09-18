"""Пересчёт связей строк BOM с библиотекой компонентов.

Связи ставятся при импорте. Если библиотеку пополнили позже, старые
составы останутся без ссылок — эта команда проходит по ним заново:

    python manage.py relink_boards            # только несвязанные строки
    python manage.py relink_boards --all      # пересчитать все
    python manage.py relink_boards --board HSBP-5S01-02C

Строки, компонент которых выбрали руками, пересчёт обходит стороной.
"""

from django.core.management.base import BaseCommand

from boards.linking import MATCH_PICK, build_index, resolve
from boards.models import BoardItem

BATCH = 500
LINK_FIELDS = ["component_table", "component_id", "component_match"]


class Command(BaseCommand):
    help = "Заново сопоставляет строки составов с записями компонентов"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true",
                            help="пересчитать и уже связанные строки")
        parser.add_argument("--board", action="append", dest="boards",
                            help="ограничиться платой с этим OY P/N")

    def handle(self, *args, **options):
        items = BoardItem.objects.all()
        if not options["all"]:
            items = items.filter(component_id__isnull=True)
        if options["boards"]:
            items = items.filter(revision__board__base_pn__in=options["boards"])

        total = items.count()
        if not total:
            self.stdout.write("Нечего пересчитывать.")
            return

        self.stdout.write(f"Строк к обработке: {total}. Строю индекс…")
        index = build_index()

        changed = linked = 0
        batch = []
        # строки читаются потоком и пишутся пачками: в больших базах их
        # сотни тысяч, и складывать все изменения в один список нельзя
        for item in items.iterator(chunk_size=BATCH):
            if not self._relink(item, index):
                continue
            batch.append(item)
            changed += 1
            linked += int(item.component_id is not None)
            if len(batch) >= BATCH:
                BoardItem.objects.bulk_update(batch, LINK_FIELDS)
                batch.clear()

        if batch:
            BoardItem.objects.bulk_update(batch, LINK_FIELDS)

        self.stdout.write(self.style.SUCCESS(
            f"Обновлено строк: {changed}, из них связано: {linked}."))

    @staticmethod
    def _relink(item, index):
        """Проставляет строке новую связь. True, если она изменилась.

        Строку, компонент которой выбрал человек, команда не трогает даже
        с ``--all``: там связь не угадана по артикулу, а указана — и
        указана бывает как раз тогда, когда записей с таким артикулом
        несколько и автоматика выбрала бы не ту.
        """
        if item.component_match == MATCH_PICK:
            return False

        found = resolve({"gbt_pn": item.gbt_pn, "vendor_pn": item.vendor_pn,
                         "vendor": item.vendor}, index)
        current = (item.component_table, item.component_id, item.component_match)
        if found == current:
            return False
        item.component_table, item.component_id, item.component_match = found
        return True
