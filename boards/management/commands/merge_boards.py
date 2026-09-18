"""Сводит платы, которые разъехались по записи номера.

Две причины, по которым одна плата оказывалась в реестре двумя строками:

* точки. ``HSFP-SCM.01`` и ``HSFP-SCM01`` — одна плата, но раньше номер
  брался как написан, и у каждой записи оказывалась своя половина ревизий;
* исполнение. Суффикс ``-R`` попадал в базовый номер, хотя это тот же
  ревизия, собранная в другом месте.

Новые импорты складываются правильно сами — номер приводится к единой
записи в ``revisions.parse_pn``. Эта команда чинит то, что уже накоплено:
переносит ревизии к одной плате и удаляет опустевшие записи.

    python manage.py merge_boards --dry-run
    python manage.py merge_boards

Сухой прогон — не формальность: слияние необратимо, а решение о том, какая
запись основная, принимается по номеру, и посмотреть на список стоит до, а
не после.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from boards.models import Board
from boards.pn import canonical
from boards.revisions import parse_pn, split_variant, variant_of


def base_of(board):
    """Каноничный номер платы — по номерам её ревизий.

    Полю ``base_pn`` доверять нельзя: у плат, заведённых до нынешних
    правил, там лежит номер ревизии целиком, с ревизиями — старый разбор
    не понимал
    номеров вида ``RBR-CRS2033R-10RF`` и оставлял их как есть.
    """
    for number in [revision.oy_pn for revision in board.revisions.all()]:
        base_pn, board_rev, bom_rev = parse_pn(number)
        if board_rev or bom_rev:          # номер разобрался как ревизия
            return base_pn
    return canonical(split_variant(board.base_pn)[0])


def refresh(revision):
    """Пересчитывает ревизии и локализацию ревизии по нынешним правилам."""
    _, board_rev, bom_rev = parse_pn(revision.oy_pn)
    variant = variant_of(revision.oy_pn)
    changed = [name for name, value in (("board_rev", board_rev),
                                        ("bom_rev", bom_rev),
                                        ("variant", variant))
               if value and getattr(revision, name) != value]
    if changed:
        for name, value in (("board_rev", board_rev), ("bom_rev", bom_rev),
                            ("variant", variant)):
            if value:
                setattr(revision, name, value)
        revision.save(update_fields=changed)
    return bool(changed)


def move_item(board, keeper):
    """Переносит позицию-двойник с лишней платы на основную.

    На плату ссылается позиция из раздела изделий, и ссылка защищённая:
    без этого шага удаление падает с ProtectedError. Если у основной платы
    своя позиция уже есть, лишнюю не удаляем молча — сначала переводим на
    неё строки состава, иначе состав изделия потерял бы плату.
    """
    from servers.models import BomLine, Item

    spare = Item.objects.filter(board=board).first()
    if spare is None:
        return

    keeper_item = (Item.objects.filter(board=keeper).exclude(pk=spare.pk).first()
                   or Item.objects.filter(oy_pn__iexact=keeper.base_pn)
                   .exclude(pk=spare.pk).first())
    if keeper_item is None:
        spare.board = keeper
        # номер меняем, только если он свободен: он уникальный, и занять
        # чужой значит уронить команду на середине
        if keeper.base_pn and not Item.objects.filter(
                oy_pn__iexact=keeper.base_pn).exclude(pk=spare.pk).exists():
            spare.oy_pn = keeper.base_pn
        spare.save(update_fields=["board", "oy_pn"])
        return

    BomLine.objects.filter(child=spare).update(child=keeper_item)
    BomLine.objects.filter(parent=spare).update(parent=keeper_item)
    spare.board = None
    spare.save(update_fields=["board"])
    spare.delete()

    if keeper_item.board_id is None:
        keeper_item.board = keeper
        keeper_item.save(update_fields=["board"])


class Command(BaseCommand):
    help = "Сводит платы с одинаковым номером, записанным по-разному"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="показать, что будет сделано, и выйти")

    def handle(self, *args, **options):
        groups = defaultdict(list)
        names = {}
        for board in Board.objects.prefetch_related("revisions"):
            base_pn = base_of(board)
            groups[base_pn.upper()].append(board)
            names.setdefault(base_pn.upper(), base_pn)

        # чинить нужно и одиночек: у платы, чей номер разбирался старыми
        # правилами, base_pn приводится к единой записи, даже если сливать
        # её не с чем
        work = {key: boards for key, boards in groups.items()
                if len(boards) > 1 or boards[0].base_pn != names[key]}
        if not work:
            self.stdout.write("реестр уже в единой записи — сливать нечего")
            return

        for key, boards in sorted(work.items()):
            listed = ", ".join(f"{b.base_pn} ({b.revisions.count()})"
                               for b in boards)
            self.stdout.write(f"{names[key]} ← {listed}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("сухой прогон, ничего не менял"))
            return

        moved = merged = renamed = 0
        with transaction.atomic():
            for key, boards in sorted(work.items()):
                # Основной оставляем ту, что уже названа правильно: тогда
                # переименовывать вообще ничего не придётся. Дальше — по
                # числу ревизий: её нумерация сохранится, а переносить
                # придётся меньше
                boards.sort(key=lambda board: (
                    board.base_pn.upper() != key, -board.revisions.count(),
                    board.pk))
                keeper, rest = boards[0], boards[1:]
                base_pn = names[key]

                for board in rest:
                    # номера ревизий у плат свои и почти наверняка
                    # совпадают — продолжаем нумерацию основной платы,
                    # иначе упрёмся в ограничение уникальности
                    last = keeper.revisions.order_by("-number").first()
                    number = (last.number + 1) if last else 1
                    for revision in board.revisions.order_by("number"):
                        revision.board = keeper
                        revision.number = number
                        _, revision.board_rev, revision.bom_rev = parse_pn(
                            revision.oy_pn)
                        revision.variant = variant_of(revision.oy_pn)
                        revision.save(update_fields=[
                            "board", "number", "board_rev", "bom_rev",
                            "variant"])
                        number += 1
                        moved += 1

                    # текущая ревизия основной платы не трогаем: какой из
                    # них считать текущим — решение человека
                    board.current_revision = None
                    board.save(update_fields=["current_revision"])
                    move_item(board, keeper)
                    board.delete()
                    merged += 1

                # Переименование — последним действием: номер уникален, и
                # пока соседка по группе жива, он занят ею. Раньше этот шаг
                # шёл первым и падал на ограничении уникальности
                if keeper.base_pn != base_pn:
                    keeper.base_pn = base_pn
                    keeper.save(update_fields=["base_pn"])
                    renamed += 1

                # ревизии и локализация у ревизий считались старыми
                # правилами — пересчитываем по нынешним
                for revision in keeper.revisions.all():
                    refresh(revision)

        self.stdout.write(self.style.SUCCESS(
            f"перенесено ревизий: {moved}, слито плат: {merged}, "
            f"приведено номеров: {renamed}"))
