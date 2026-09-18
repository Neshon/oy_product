"""Перенос карточек из Confluence.

На вход идёт JSON, который готовит ``tools/confluence_parse.py``. Почему
через файл, а не напрямую из markdown: разбор выгрузки — то, что придётся
править чаще всего (разметка страниц разъезжается от шаблона к шаблону), и
держать его отдельно от записи в базу дешевле. Заодно JSON можно посмотреть
глазами до того, как что-то попадёт в таблицы.

Что откуда берётся:

* страницы моделей   -> позиции-серверы и их состав;
* страницы плат      -> позиции-платы (или дополняют уже заведённые);
* карточки печатных узлов -> сюда не попадают вовсе: ревизиями ведает
  раздел плат, и их карточки грузит ``manage.py import_cards`` прямо из
  markdown;
* карточки кабелей   -> позиции-кабели с длиной, типом и AWG.

Партномера в Confluence пишутся то с точками, то без (``HSBP-4L.01`` и
``HSBP-4L01``), поэтому сопоставление идёт по номеру без точек.
"""

import json

from boards.pn import match_key

from .models import BomLine, Item

SOURCE = "confluence"

KINDS = {"server": Item.SERVER, "board": Item.BOARD, "cable": Item.CABLE}

# поле карточки -> поле позиции. Остальное уходит в details как есть
NAME_FIELDS = ("Полное наименование", "Полное наименование (партномер)")
DECIMAL_FIELDS = ("Децимальный номер изделия",
                  "Децимальный номер узла печатного (PCBA)",
                  "Децимальный номер")


def _first(fields, names):
    for name in names:
        if fields.get(name):
            return fields[name]
    return ""


class Loader:
    """Переносит разобранный экспорт. Ведёт отчёт по ходу дела."""

    def __init__(self):
        self.report = {"created": [], "updated": [], "lines": 0,
                       "skipped": []}
        # индекс строится один раз: позиций сотни, и искать каждую
        # отдельным запросом незачем
        self.index = {match_key(item.oy_pn): item for item in Item.objects.all()}

    def find(self, part_number):
        return self.index.get(match_key(part_number))

    def item_for_board(self, part_number):
        """Позиция-двойник платы из реестра.

        Плату к этому времени должен был завести ``import_cards``, и
        позиция должна ссылаться на неё: иначе в базе окажутся две записи
        с одним номером — плата в реестре и позиция в составе, — и связать
        их потом будет нечем.

        Платы нет — заводим обычную позицию: состав изделия важнее связи
        с реестром, а связь потом восстановит ``sync_boards``.
        """
        from boards.models import Board
        from boards.revisions import parse_pn

        from .boards_bridge import sync_board

        base_pn, _, _ = parse_pn(part_number)
        board = Board.objects.filter(base_pn__iexact=base_pn).first()
        if board is None:
            return self.item_for(part_number, Item.BOARD)

        known = match_key(board.base_pn) in self.index
        item = sync_board(board)
        self.index[match_key(item.oy_pn)] = item
        return item, not known

    def item_for(self, part_number, kind, name="", source=SOURCE):
        """Позиция по номеру; чего нет — заводится заготовкой."""
        found = self.find(part_number)
        if found is not None:
            return found, False
        item = Item.objects.create(oy_pn=part_number, kind=kind,
                                   name=name or part_number, source=source)
        self.index[match_key(part_number)] = item
        return item, True

    def save_card(self, page):
        """Карточка страницы -> позиция."""
        kind = KINDS.get(page["kind"])
        if kind is None:
            return None

        fields = page.get("fields") or {}
        if kind == Item.BOARD:
            # у платы уже есть запись в реестре — позиция должна ссылаться
            # на неё, а не заводиться второй записью с тем же номером
            item, created = self.item_for_board(page["oy_pn"])
        else:
            item, created = self.item_for(page["oy_pn"], kind,
                                          page.get("name") or "")

        # Ручную правку не затираем: импорт дополняет карточку, а не
        # переписывает её. Иначе повторная заливка сотрёт то, что люди
        # исправили после первой
        if page.get("name") and not item.name:
            item.name = page["name"][:255]
        if not item.decimal_number:
            item.decimal_number = _first(fields, DECIMAL_FIELDS)[:128]
        if not item.description:
            item.description = _first(fields, NAME_FIELDS)

        details = dict(item.details or {})
        for key, value in fields.items():
            details.setdefault(key, value)
        details.setdefault("Страница Confluence", page.get("source", ""))
        item.details = details
        if not item.source:
            item.source = SOURCE
        item.save()

        self.report["created" if created else "updated"].append(item)
        return item

    def save_line(self, line):
        """Строка состава из карточки модели."""
        parent = self.find(line["parent"])
        if parent is None:
            self.report["skipped"].append((line["parent"], "нет карточки изделия"))
            return

        child, _ = self.item_for(line["child"], Item.BOARD)
        if child.pk == parent.pk:
            return

        BomLine.objects.update_or_create(
            parent=parent, child=child, source=SOURCE,
            defaults={"quantity": line.get("quantity") or 1, "unit": "шт",
                      "comment": line.get("comment", ""),
                      "oy_pn": child.oy_pn})
        self.report["lines"] += 1

    def load(self, data, replace=True):
        pages = data.get("items", [])

        # сначала карточки: строки состава должны находить, на что ссылаться
        for page in pages:
            if page["kind"] in KINDS:
                self.save_card(page)
        if replace:
            # только прежний импорт из Confluence; руками заведённые строки
            # и строки из System BOM остаются на месте
            BomLine.objects.filter(source=SOURCE).delete()
        for line in data.get("bom", []):
            self.save_line(line)

        return self.report


def load_file(path, replace=True):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return Loader().load(data, replace=replace)
