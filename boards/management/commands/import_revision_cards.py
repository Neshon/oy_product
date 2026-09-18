"""Заполнение карточек выпусков из страниц Confluence в markdown.

    python manage.py import_revision_cards ./pages --dry-run
    python manage.py import_revision_cards ./pages/*.md
    python manage.py import_revision_cards hsbp-5s01-02c.md hsbp-5s01-10e.md

Принимает и каталог, и шаблон, и отдельные файлы. Шаблон раскрывается
самой командой: в cmd и PowerShell оболочка этого не делает, и Python
получал бы строку «*.md» как имя файла.

Номер выпуска берётся из заголовка страницы, а не из имени файла: файлы
называют как придётся, а заголовок — это сам партномер. По нему находится
плата и её выпуск; если выпуска ещё нет, он заводится с пустым составом —
состав приходит импортом BOM, а карточка живёт своей жизнью.

Заполняются только пустые поля. Страницы верстают люди, и в них хватает
недозаполненного; затирать то, что уже поправили руками, импорт не должен.
Ключ --force меняет это правило, если нужно перелить страницу поверх.
"""

import glob
import pathlib
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boards import checklists, md_card
from boards.models import Board, BoardRevision, ChecklistItem
from boards.revisions import canonical, parse_pn, variant_of


def normalize(title):
    """Название документа для сравнения: регистр и пробелы не в счёт."""
    return " ".join((title or "").lower().replace("ё", "е").split())


def short(title):
    """То же, но без уточнения в скобках.

    На страницах документ называют подробнее, чем в шаблоне: «Инструкция по
    тестированию плат (в том числе чтению логов)» — это та же строка, что и
    «Инструкция по тестированию плат». Без такого сравнения рядом с
    шаблонной строкой заводилась бы вторая, почти такая же.
    """
    return normalize(re.sub(r"\([^)]*\)", " ", title or ""))


class Command(BaseCommand):
    help = "Заполняет карточки выпусков из markdown-страниц Confluence"

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+",
                            help="файлы .md, каталог с ними или шаблон вида *.md")
        parser.add_argument("--dry-run", action="store_true",
                            help="разобрать и показать, ничего не записывая")
        parser.add_argument("--force", action="store_true",
                            help="перезаписывать уже заполненные поля")

    def handle(self, *args, **options):
        files = self.files(options["paths"])
        if not files:
            raise CommandError(
                "Не нашёл ни одного файла .md по указанным путям.")

        self.stdout.write(f"страниц к разбору: {len(files)}")
        for path in files:
            data = md_card.parse(path.read_text(encoding="utf-8"), path.name)
            self.one(path, data, options)

    def files(self, paths):
        """Раскрывает каталоги и шаблоны в список файлов.

        Раскрываем сами: в cmd и PowerShell оболочка шаблоны не разворачивает,
        и «./pages/*.md» доехало бы до open() как имя файла.
        """
        found = []
        for path in paths:
            item = pathlib.Path(path)
            if item.is_dir():
                found += sorted(item.rglob("*.md"))
            elif any(sign in path for sign in "*?["):
                found += sorted(pathlib.Path(name) for name in glob.glob(path))
            elif item.exists():
                found.append(item)
            else:
                self.stderr.write(self.style.WARNING(f"нет такого файла: {path}"))

        # один и тот же файл мог прийти и каталогом, и шаблоном
        unique = {item.resolve(): item for item in found if item.is_file()}
        return [unique[key] for key in sorted(unique)]

    def one(self, path, data, options):
        number = data["number"]
        self.stdout.write(f"\n{path}: {number}")
        self.stdout.write(
            f"   полей карточки {len(data['card']) + len(data['numbers'])}, "
            f"ссылок {len(data['links'])}, "
            f"строк чек-листов {len(data['checklist'])} "
            f"(со статусом {sum(1 for r in data['checklist'] if r['status'])})")

        if options["dry_run"]:
            for key, value in sorted(data["card"].items()):
                self.stdout.write(f"      {key} = {value}")
            return

        with transaction.atomic():
            revision = self.revision_for(number)
            changed = self.fill(revision, data, options["force"])
            added, touched = self.checklist(revision, data["checklist"],
                                            options["force"])

        self.stdout.write(self.style.SUCCESS(
            f"   заполнено полей: {changed}, строк чек-листов: {touched}"
            + (f", добавлено строк: {added}" if added else "")))

    def revision_for(self, number):
        """Выпуск по номеру; платы или выпуска нет — заводим."""
        base_pn, _, _ = parse_pn(number)
        board = Board.objects.filter(base_pn__iexact=base_pn).first()
        if board is None:
            board = Board(base_pn=base_pn, oy_pn=number)
            board.apply_pn(number)
            board.save()
            self.stdout.write(f"   заведена плата {board.base_pn}")

        # Номер сравниваем без точек: одну и ту же ревизию пишут и
        # «HSBP-5S.01-01A», и «HSBP-5S01-01A». Иначе на вторую страницу
        # заводится второй выпуск — с тем же составом и теми же
        # чек-листами
        wanted = canonical(normalize(number))
        revision = next(
            (item for item in board.revisions.all()
             if canonical(normalize(item.oy_pn)) == wanted), None)
        if revision is None:
            last = board.revisions.order_by("-number").first()
            revision = BoardRevision(board=board,
                                     number=(last.number + 1) if last else 1)
            revision.apply_pn(number)
            revision.source_file = "confluence"
            revision.save()
            checklists.ensure(revision)
            self.stdout.write("   заведён выпуск без состава")
        revision.variant = variant_of(revision.oy_pn)
        return revision

    def fill(self, revision, data, force):
        values = dict(data["card"], **data["numbers"], **data["links"])
        if data["approved"]:
            values["approved"] = True

        changed = ["variant"]
        for name, value in values.items():
            if not hasattr(revision, name) or value in ("", None):
                continue
            if force or not getattr(revision, name):
                setattr(revision, name, value)
                changed.append(name)
        revision.save(update_fields=sorted(set(changed)))

        # полное наименование описывает плату, а не выпуск: «Бэкплейн
        # HSBP-5S.01» одинаково у всех её выпусков
        board = revision.board
        if data["name"] and (force or not board.name):
            board.name = data["name"][:255]
            board.save(update_fields=["name"])

        return len(changed) - 1

    def checklist(self, revision, rows, force):
        """Переносит ответы в строки чек-листов выпуска."""
        checklists.ensure(revision)

        known = {}
        for item in revision.checklist.all():
            known.setdefault((item.group, normalize(item.title)), item)
            known.setdefault((item.group, short(item.title)), item)

        added = touched = 0
        for position, row in enumerate(rows, start=100):
            item = (known.get((row["group"], normalize(row["title"])))
                    or known.get((row["group"], short(row["title"])))
                    # строка могла остаться от прошлого запуска: он мог
                    # оборваться на середине, а файлы пишутся по одному
                    or ChecklistItem.objects.filter(
                        revision=revision, group=row["group"],
                        title=row["title"][:255]).first())
            if item is None:
                # документа нет в шаблоне: на странице он есть, значит
                # нужен — заводим строкой этого выпуска
                item = ChecklistItem(
                    revision=revision, group=row["group"], position=position,
                    title=row["title"][:255],
                    responsibility=row["responsibility"][:255])
                added += 1
                # Запоминаем сразу: на одной странице документ встречается
                # дважды — в разных разделах или с уточнением в скобках, — и
                # вторая строка иначе завела бы дубль. База такого не
                # допускает: (выпуск, группа, название) уникальны
                known[(row["group"], normalize(row["title"]))] = item
                known[(row["group"], short(row["title"]))] = item

            changed = False
            for name in ("status", "comment", "url", "file_format"):
                value = row.get(name) or ""
                if value and (force or not getattr(item, name, "")):
                    setattr(item, name, value[:500])
                    changed = True
            if not item.responsibility and row["responsibility"]:
                item.responsibility = row["responsibility"][:255]
                changed = True

            if changed or item.pk is None:
                item.save()
                touched += 1
        return added, touched
