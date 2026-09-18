"""Чем состав ревизии отличается от предыдущей.

Сравниваются основные строки по ключу: GBT P/N, а если его нет — Vendor P/N.
Замены в сравнение не идут: они привязаны к позиции и меняются вместе с ней.
"""

from .models import BoardItem

# какие поля читать у предыдущей ревизии: для сравнения нужны ключ и
# количество, а описания и обозначения — уже нет
COMPARED_FIELDS = ("id", "revision_id", "position", "kind", "gbt_pn",
                   "vendor_pn", "qty")


def _key(item):
    return (item.gbt_pn or item.vendor_pn or "").strip().lower()


def revision_diff(previous, items):
    """Возвращает ``{"added", "removed", "changed"}`` или None, если равны.

    ``items`` — состав текущей ревизии, уже прочитанный для показа;
    предыдущая ревизия читается здесь, и только теми полями, которые
    участвуют в сравнении и в выводе.
    """
    was = {}
    for item in (previous.items.filter(kind=BoardItem.MAIN)
                 .only(*COMPARED_FIELDS)):
        key = _key(item)
        if key:
            was[key] = item

    now = {_key(i): i for i in items if i.is_main and _key(i)}

    added = [now[k] for k in now.keys() - was.keys()]
    removed = [was[k] for k in was.keys() - now.keys()]
    changed = [(was[k], now[k]) for k in was.keys() & now.keys()
               if was[k].qty != now[k].qty]

    if not (added or removed or changed):
        return None
    return {"added": added, "removed": removed, "changed": changed}
