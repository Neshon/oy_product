"""Заполнение карточек платы и ревизии из страниц Confluence в markdown.

    python manage.py import_cards ./pages --dry-run
    python manage.py import_cards ./pages/*.md
    python manage.py import_cards hsbp-5s01.md hsbp-5s01-02c.md

Вид страницы определяется по содержимому, а не по имени файла: «Карточка
печатного узла» — ревизия, «Список версий печатных плат» — плата. Поэтому
каталог можно скормить целиком, вперемешку.

Принимает и каталог, и шаблон, и отдельные файлы. Шаблон раскрывается
самой командой: в cmd и PowerShell оболочка этого не делает, и Python
получал бы строку «*.md» как имя файла.

Номер ревизии берётся из заголовка страницы, а не из имени файла: файлы
называют как придётся, а заголовок — это сам партномер. По нему находится
плата и её ревизия; если ревизии ещё нет, он заводится с пустым составом —
состав приходит импортом BOM, а карточка живёт своей жизнью.

Заполняются только пустые поля. Страницы верстают люди, и в них хватает
недозаполненного; затирать то, что уже поправили руками, импорт не должен.
Ключ --force меняет это правило, если нужно перелить страницу поверх.
"""

import glob
import pathlib
import re

from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boards import checklists, images, md_card
from boards.models import Board, BoardRevision
from boards.pn import match_key
from boards.revisions import parse_pn, variant_of


def title_key(title):
    """Название документа для сравнения: регистр и пробелы не в счёт.

    Именно название документа, а не номер: для номеров есть
    :func:`boards.pn.match_key`. Раньше функция называлась ``normalize``,
    и номер ревизии однажды уехал сравниваться через неё — работало по
    случайности, потому что обе стороны шли через одну и ту же обработку.
    """
    return " ".join((title or "").lower().replace("ё", "е").split())


def short(title):
    """То же, но без уточнения в скобках.

    На страницах документ называют подробнее, чем в шаблоне: «Инструкция по
    тестированию плат (в том числе чтению логов)» — это та же строка, что и
    «Инструкция по тестированию плат». Без такого сравнения рядом с
    шаблонной строкой заводилась бы вторая, почти такая же.
    """
    return title_key(re.sub(r"\([^)]*\)", " ", title or ""))


# Куда выгрузка Confluence кладёт картинки страницы — рядом с самим
# markdown. Относительный путь в тексте (`./attachments/plate.png`) и полный
# адрес с сервера ведут к одному и тому же файлу здесь.
ATTACHMENTS = "attachments"


class Command(BaseCommand):
    help = "Заполняет карточки плат и ревизий из markdown-страниц Confluence"

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
            text = path.read_text(encoding="utf-8")
            if md_card.is_board_page(text):
                self.board(path, md_card.parse_board(text, path.name), options)
            else:
                self.one(path, md_card.parse(text, path.name), options)

    def board(self, path, data, options):
        """Страница платы: наименование, описание, характеристика."""
        number = data["number"]
        # board_type и developer раньше умел только импорт из JSON; теперь
        # путь один, и терять их нельзя
        filled = {name: data.get(name) for name in
                  ("name", "board_type", "developer",
                   "purpose", "applicability", "specs") if data.get(name)}
        self.stdout.write(f"\n{path}: плата {number}")
        self.stdout.write(f"   заполнено полей: {len(filled)} "
                          f"({', '.join(sorted(filled)) or '—'})")

        if options["dry_run"]:
            ready = self.ready_photos(path, data.get("images") or [])
            self.stdout.write(f"   картинки: {', '.join(ready) or '—'}")
            return

        with transaction.atomic():
            base_pn, _, _ = parse_pn(number)
            board = Board.objects.filter(base_pn__iexact=base_pn).first()
            if board is None:
                board = Board(base_pn=base_pn)
                board.save()
                self.stdout.write("   заведена плата без ревизий")

            changed = []
            for name, value in filled.items():
                if options["force"] or not getattr(board, name):
                    setattr(board, name,
                            value[:255] if name in ("name", "developer") else value)
                    changed.append(name)
            if changed:
                board.save(update_fields=changed)

            photos = self.photos(board, path, data.get("images") or [],
                                 options["force"])

        self.stdout.write(self.style.SUCCESS(
            f"   записано полей: {len(changed)}"
            + (f", картинок: {len(photos)} ({', '.join(photos)})"
               if photos else "")))

    def ready_photos(self, path, names):
        """Какие картинки со страницы действительно лежат рядом, первые две."""
        folder = path.parent / ATTACHMENTS
        return [name for name in names if (folder / name).is_file()][:2]

    def photos(self, target, path, names, force):
        """Кладёт первые две картинки страницы в поля Top side и Bottom side.

        Файлы ищем рядом с самой страницей, в ``attachments``: выгрузка
        Confluence раскладывает их именно так, а в тексте страницы адрес
        бывает и относительным, и полным — имя файла в обоих случаях одно
        (:func:`md_card.image_names`).

        Отбираем по наличию на диске, и только потом берём первые две.
        Порядок обратный был бы хрупким: на странице ревизии между
        карточкой и вложениями попадается служебная картинка Confluence
        (значок ожидания в блоке загрузки), и по позиции она могла бы
        вытеснить настоящий снимок. Среди вложений её нет.

        Возвращает список того, что записалось.
        """
        folder = path.parent / ATTACHMENTS
        found = [folder / name for name in self.ready_photos(path, names)]

        if not found:
            if names:
                self.stdout.write(self.style.WARNING(
                    f"   картинки со страницы не найдены в {folder}"))
            return []

        written = []
        for field, source in zip(("photo_top", "photo_bottom"), found):
            if getattr(target, field) and not force:
                continue
            try:
                self.save_photo(target, field, source)
            except ValidationError as exc:
                # одна негодная картинка не повод ронять импорт страницы:
                # остальное с неё пригодится
                self.stdout.write(self.style.WARNING(
                    f"   {source.name}: {'; '.join(exc.messages)}"))
                continue
            written.append(f"{field}={source.name}")
        return written

    @staticmethod
    def save_photo(target, field, source):
        """Проверяет, уменьшает и сохраняет один файл.

        Та же обработка, что при загрузке через форму (images.check и
        images.shrink): предпросмотру не нужен исходник на 12 мегабайт, а
        картинку боком надо развернуть по EXIF. Без этого импорт заливал бы
        в базу совсем другие файлы, чем форма.
        """
        with source.open("rb") as handle:
            upload = File(handle, name=source.name)
            images.check(upload)
            smaller = images.shrink(upload)
            getattr(target, field).save(source.name, smaller, save=False)
        target.save(update_fields=[field])

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
            ready = self.ready_photos(path, data.get("images") or [])
            self.stdout.write(f"      картинки = {', '.join(ready) or '—'}")
            return

        with transaction.atomic():
            revision = self.revision_for(number)
            changed = self.fill(revision, data, options["force"])
            added, touched = self.checklist(revision, data["checklist"],
                                            options["force"])
            # Снимки ревизии, а не платы: страница ревизии показывает именно
            # эту версию, и монтаж на ней свой
            photos = self.photos(revision, path, data.get("images") or [],
                                 options["force"])

        self.stdout.write(self.style.SUCCESS(
            f"   заполнено полей: {changed}, строк чек-листов: {touched}"
            + (f", добавлено строк: {added}" if added else "")
            + (f", картинок: {len(photos)} ({', '.join(photos)})"
               if photos else "")))

    def revision_for(self, number):
        """Ревизия по номеру; платы или ревизии нет — заводим."""
        base_pn, _, _ = parse_pn(number)
        board = Board.objects.filter(base_pn__iexact=base_pn).first()
        if board is None:
            board = Board(base_pn=base_pn)
            board.save()
            self.stdout.write(f"   заведена плата {board.base_pn}")

        # Номер сравниваем без точек: одну и ту же ревизию пишут и
        # «HSBP-5S.01-01A», и «HSBP-5S01-01A». Иначе на вторую страницу
        # заводится второй ревизия — с тем же составом и теми же
        # чек-листами
        wanted = match_key(number)
        revision = next(
            (item for item in board.revisions.all()
             if match_key(item.oy_pn) == wanted), None)
        if revision is None:
            last = board.revisions.order_by("-number").first()
            revision = BoardRevision(board=board,
                                     number=(last.number + 1) if last else 1)
            revision.apply_pn(number)
            # BOM у такой ревизии нет: она заведена по карточке Confluence,
            # чтобы страница не потерялась. Отметка о загрузке остаётся
            # пустой до первого файла
            revision.save()
            self.stdout.write("   заведена ревизия без состава")
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

        # полное наименование описывает плату, а не ревизию: «Бэкплейн
        # HSBP-5S.01» одинаково у всех её ревизий. Тип платы выводится
        # оттуда же — отдельным полем его на страницах не пишут
        board = revision.board
        board_changed = []
        if data["name"] and (force or not board.name):
            board.name = data["name"][:255]
            board_changed.append("name")
        if data.get("board_type") and (force or not board.board_type):
            board.board_type = data["board_type"]
            board_changed.append("board_type")
        if board_changed:
            board.save(update_fields=board_changed)

        return len(changed) - 1

    def checklist(self, revision, rows, force):
        """Переносит ответы со страницы в чек-листы ревизии.

        Сопоставление по названию документа: на странице оно написано
        свободно — с уточнением в скобках, в другом регистре, с «ё». Строки
        шаблона ищем по приведённому названию, всё прочее заводим своей
        строкой — документ на странице есть, значит он нужен.
        """
        known = {}
        for row in checklists.rows_for(revision):
            known.setdefault((row.group, title_key(row.title)), row)
            known.setdefault((row.group, short(row.title)), row)

        updates, added, touched = {}, 0, 0
        for row in rows:
            group, title = row["group"], row["title"][:255]
            found = (known.get((group, title_key(row["title"])))
                     or known.get((group, short(row["title"]))))

            if found is None:
                # Документа нет ни в шаблоне, ни среди уже сохранённых:
                # заводим строку этой ревизии вместе с описанием — взять
                # его больше неоткуда.
                checklists.describe(revision, group, title, {
                    "responsibility": row.get("responsibility", "")[:255],
                    "file_format": row.get("file_format", "")[:64],
                })
                found = checklists.Row(group=group, title=title, extra=True)
                added += 1
                # Запоминаем сразу: на одной странице документ встречается
                # дважды — в разных разделах или с уточнением в скобках, — и
                # вторая строка иначе перетёрла бы первую
                known[(group, title_key(row["title"]))] = found
                known[(group, short(row["title"]))] = found

            key = (found.group, found.title)
            answer = updates.get(key) or {
                "status": found.status, "comment": found.comment,
                "url": found.url}
            changed = False
            for name in ("status", "comment", "url"):
                value = (row.get(name) or "")[:500]
                if value and (force or not answer.get(name)):
                    answer[name] = value
                    changed = True
            updates[key] = answer
            if changed:
                touched += 1

        # одна запись на всю страницу вместо сохранения каждой строки
        checklists.save_answers(revision, updates)
        return added, touched
