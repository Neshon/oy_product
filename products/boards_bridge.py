"""Позиции для плат.

Плата ведётся в своём разделе и там ей хорошо: ревизии, импорт BOM,
сравнение ревизий. Но в составе сервера она должна быть позицией — иначе
строка «в сервер входит материнская плата» не с чем связать.

Поэтому на каждую плату заводится позиция-двойник. Своего состава она не
хранит: он берётся из текущей ревизии платы (см. ``bom_edge``). Синхронизация
идёт в одну сторону — от платы к позиции: номер, название и децимальный
номер платы главнее, их правят в разделе плат.

Вызывается после импорта BOM и командой ``sync_boards``. Отдельной командой
нужна потому, что платы заводятся и мимо импорта — руками и чужими
скриптами.
"""

from .models import Item

def sync_board(board):
    """Заводит или обновляет позицию для одной платы."""
    # позиция представляет плату, а не её ревизия: номер у неё базовый,
    # без ревизии
    number = board.base_pn

    item = Item.objects.filter(board=board).first()
    if item is None:
        # номер мог быть занят позицией, заведённой раньше импортом состава:
        # там плата упоминалась строкой, а карточки ещё не было
        item = (Item.objects.filter(oy_pn__iexact=number).first()
                or Item())
        item.board = board

    # чужой номер не отбираем: он уникальный, и попытка занять его уронила
    # бы сохранение
    taken = Item.objects.filter(oy_pn__iexact=number)
    if item.pk:
        taken = taken.exclude(pk=item.pk)
    if not taken.exists():
        item.oy_pn = number
    item.kind = Item.BOARD
    if not item.name:
        item.name = board.name or board.base_pn
    if not item.source:
        item.source = "раздел плат"
    item.save()
    return item


def sync_all():
    """Проходит по всем платам. Возвращает (заведено, обновлено)."""
    from boards.models import Board

    created = updated = 0
    known = set(Item.objects.filter(board__isnull=False)
                .values_list("board_id", flat=True))
    for board in Board.objects.all():
        sync_board(board)
        if board.id in known:
            updated += 1
        else:
            created += 1
    return created, updated
