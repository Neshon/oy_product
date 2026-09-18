"""Сводит исполнения в одну плату.

До правила «исполнение — признак выпуска» суффикс ``-R`` попадал в базовый
номер, и ``HSBP-4L01`` с ``HSBP-4L01-R`` заводились как две платы. Реестр
показывал две строки там, где плата одна, и выпуски делились между ними
пополам.

Новые импорты складываются правильно сами. Эта команда чинит то, что уже
накоплено: переносит выпуски исполнения к основной плате и удаляет
опустевшую запись.

    python manage.py merge_variants --dry-run
    python manage.py merge_variants

Сухой прогон — не формальность: слияние необратимо, а решение о том, какая
плата основная, принимается по номеру, и посмотреть на этот список стоит
до, а не после.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from boards.models import Board
from boards.revisions import split_variant, variant_of


def move_item(board, keeper):
    """Переносит позицию-двойник с исполнения на основную плату.

    На плату ссылается позиция из раздела изделий, и ссылка защищённая:
    без этого шага удаление падает с ProtectedError. Если у основной платы
    своя позиция уже есть, лишнюю не удаляем молча — сначала переводим на
    неё строки состава, иначе состав изделия потерял бы плату.
    """
    from products.models import BomLine, Item

    spare = Item.objects.filter(board=board).first()
    if spare is None:
        return

    keeper_item = (Item.objects.filter(board=keeper).exclude(pk=spare.pk).first()
                   or Item.objects.filter(oy_pn__iexact=keeper.oy_pn)
                   .exclude(pk=spare.pk).first())
    if keeper_item is None:
        # у основной платы позиции нет — просто переводим стрелку.
        # Номер меняем, только если он свободен: он уникальный, и занять
        # чужой значит уронить всю команду на середине
        spare.board = keeper
        if keeper.oy_pn and not Item.objects.filter(
                oy_pn__iexact=keeper.oy_pn).exclude(pk=spare.pk).exists():
            spare.oy_pn = keeper.oy_pn
        spare.save(update_fields=["board", "oy_pn"])
        return

    # у основной платы позиция уже есть: состав, который ссылался на
    # исполнение, переводим на неё, и только потом убираем лишнюю
    BomLine.objects.filter(child=spare).update(child=keeper_item)
    BomLine.objects.filter(parent=spare).update(parent=keeper_item)
    spare.board = None
    spare.save(update_fields=["board"])
    spare.delete()

    if keeper_item.board_id is None:
        keeper_item.board = keeper
        keeper_item.save(update_fields=["board"])


class Command(BaseCommand):
    help = "Переносит выпуски исполнений (-R) к основной плате"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="показать, что будет сделано, и выйти")

    def handle(self, *args, **options):
        pairs = []
        for board in Board.objects.all():
            base_pn, variant = split_variant(board.base_pn)
            if variant:
                pairs.append((board, base_pn))

        if not pairs:
            self.stdout.write("исполнений отдельными платами не нашлось")
            return

        for board, base_pn in pairs:
            keeper = Board.objects.filter(base_pn__iexact=base_pn).first()
            target = keeper.base_pn if keeper else f"{base_pn} (будет заведена)"
            self.stdout.write(
                f"{board.base_pn}: выпусков {board.revisions.count()} → {target}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("сухой прогон, ничего не менял"))
            return

        moved = merged = 0
        with transaction.atomic():
            for board, base_pn in pairs:
                # Основную плату ищем заново, а не берём из списка выше:
                # предыдущий шаг цикла мог её только что завести — два
                # исполнения одной платы (с точками в номере и без)
                # встречаются в одной базе
                keeper = Board.objects.filter(base_pn__iexact=base_pn).first()
                if keeper is None:
                    # основной платы нет вовсе: достаточно переименовать
                    board.base_pn = base_pn
                    board.save(update_fields=["base_pn"])
                    for revision in board.revisions.all():
                        revision.variant = variant_of(revision.oy_pn)
                        revision.save(update_fields=["variant"])
                    continue

                # номера выпусков у плат свои и почти наверняка совпадают —
                # продолжаем нумерацию основной платы, иначе упрёмся в
                # ограничение уникальности (плата, номер)
                last = keeper.revisions.order_by("-number").first()
                number = (last.number + 1) if last else 1
                for revision in board.revisions.order_by("number"):
                    revision.board = keeper
                    revision.number = number
                    revision.variant = variant_of(revision.oy_pn)
                    revision.save(update_fields=["board", "number", "variant"])
                    number += 1
                    moved += 1

                # текущий выпуск у основной платы менять не будем: какой из
                # двух исполнений считать текущим — решение человека
                board.current_revision = None
                board.save(update_fields=["current_revision"])
                move_item(board, keeper)
                board.delete()
                merged += 1

        self.stdout.write(self.style.SUCCESS(
            f"перенесено выпусков: {moved}, слито плат: {merged}"))
