"""Карточки плат и ревизий из выгрузки Confluence.

На вход идёт тот же JSON, что и для позиций (``tools/confluence_parse.py``).
Отсюда берутся страницы двух видов:

* страница платы со списком версий -> :class:`~boards.models.Board`;
* карточка печатного узла          -> :class:`~boards.models.BoardRevision`.

Плата и ревизия заводятся, даже если BOM ещё не загружали: реестр должен
показывать плату, о которой есть документация, а не только ту, по которой
пришёл файл. Состав у такой ревизии пустой — он появится с импортом BOM.

Импорт **дополняет, а не переписывает**: заполняются только пустые поля.
Иначе повторная заливка стёрла бы то, что люди поправили руками, а поправят
они наверняка — часть значений в выгрузке оформлена как попало.
"""

import re

from .models import Board, BoardRevision
from .pn import match_key
from .revisions import parse_pn, variant_of

SOURCE = "confluence"

# поле карточки Confluence -> поле ревизии
REVISION_FIELDS = {
    "Наименование печатной платы (PCB)": "pcb_name",
    "Наименование BOM": "bom_name",
    "Обозначение на шелкографии": "silkscreen",
    "Децимальный номер узла печатного (PCBA)": "decimal_pcba",
    "Децимальный номер печатной платы (PCB)": "decimal_pcb",
    "Вид печатной платы (из ПП РФ №719)": "pcb_type",
    "Наименование ресурсной спецификации (1С)": "spec_1c",
    "Ссылка на ресурсную спецификацию (1С)": "spec_1c_url",
    "FRU-шаблон модели печатного узла (MegaRAC)": "fru_megarac",
    "FRU-шаблон модели печатного узла (OYBMC)": "fru_oybmc",
    "Маршрут инструкций": "instructions_url",
}

# Числовые поля карточки. В выгрузке они приходят с хвостом («2 шт»,
# «140 баллов»), поэтому берётся первое число, а не значение целиком
NUMBERS = {
    "Количество плат в мультизаготовке": "panel_count",
    "Количество баллов": "points",
}

# «Бэкплейн HSBP-4L.01» -> backplane. Тип платы в выгрузке отдельным полем
# не записан, зато он стоит первым словом полного наименования
TYPE_WORDS = (
    ("материнск", "motherboard"),
    ("бэкплейн", "backplane"),
    ("бекплейн", "backplane"),
    ("райзер", "riser"),
    ("интерпозер", "interposer"),
    ("адаптер", "adapter"),
    ("управлен", "control"),
    ("индикац", "indicator"),
    ("питания", "power"),
)


def board_type_of(name):
    lowered = (name or "").lower()
    for word, kind in TYPE_WORDS:
        if word in lowered:
            return kind
    return ""


def _fill(instance, values):
    """Заполняет только пустые поля. Возвращает список изменённых."""
    changed = []
    for name, value in values.items():
        if not value:
            continue
        if not getattr(instance, name, None):
            setattr(instance, name, value)
            changed.append(name)
    return changed


class Loader:

    def __init__(self):
        self.report = {"boards": 0, "revisions": 0, "skipped": []}
        # индекс по номеру без точек: плату ищем и по базовому номеру, и по
        # номеру любого её ревизии
        self.boards = {match_key(board.base_pn): board
                       for board in Board.objects.all()}

    def board_for(self, part_number):
        base_pn, _, _ = parse_pn(part_number)
        key = match_key(base_pn)
        board = self.boards.get(key)
        if board is None:
            board = Board(base_pn=base_pn)
            board.save()
            self.boards[key] = board
            self.report["boards"] += 1
        return board

    def save_board(self, page):
        """Страница платы: имя и назначение — общие для всех ревизий."""
        board = self.board_for(page["oy_pn"])
        fields = page.get("fields") or {}
        name = page.get("name") or fields.get("Полное наименование") or ""
        changed = _fill(board, {
            "name": name[:255],
            "board_type": board_type_of(name),
            "developer": fields.get("Компания-разработчик", "")[:255],
            "purpose": fields.get("Назначение", ""),
            "applicability": fields.get("Применяемость", ""),
        })
        if changed:
            board.save(update_fields=changed)

    def save_revision(self, page):
        """Карточка печатного узла: ревизия конкретной платы."""
        number = page["oy_pn"]
        board = self.board_for(number)
        fields = page.get("fields") or {}

        revision = next(
            (item for item in board.revisions.all()
             if match_key(item.oy_pn) == match_key(number)), None)
        if revision is None:
            last = board.revisions.order_by("-number").first()
            revision = BoardRevision(board=board,
                                     number=(last.number + 1) if last else 1)
            revision.apply_pn(number)
            revision.source_file = SOURCE
            revision.save()
            self.report["revisions"] += 1

        values = {target: fields.get(source, "")
                  for source, target in REVISION_FIELDS.items()}

        changed = _fill(revision, values)

        for source, target in NUMBERS.items():
            found = re.match(r"\d+", fields.get(source, ""))
            if found and getattr(revision, target) is None:
                setattr(revision, target, int(found.group()))
                changed.append(target)
        if revision.variant != variant_of(revision.oy_pn):
            revision.variant = variant_of(revision.oy_pn)
            changed.append("variant")
        if changed:
            revision.save(update_fields=list(set(changed)))

        # полное наименование ревизии описывает саму плату: «Бэкплейн
        # HSBP-4L.01» — это про плату, а не про её ревизия
        name = fields.get("Полное наименование", "")
        if name and not board.name:
            board.name = name[:255]
            board.board_type = board.board_type or board_type_of(name)
            board.save(update_fields=["name", "board_type"])

    def load(self, data):
        for page in data.get("items", []):
            if page["kind"] == "board":
                self.save_board(page)
        for page in data.get("items", []):
            if page["kind"] == "board_revision":
                self.save_revision(page)
        return self.report
