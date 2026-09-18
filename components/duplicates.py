"""Поиск дублей в библиотеке.

Три независимые проверки:

* **vendor** — один и тот же артикул производителя (Vendor PN + Vendor)
  заведён в нескольких записях. Обычно это одна и та же деталь, введённая
  дважды или попавшая не в свою подгруппу;
* **gbt** — совпадает внутренний номер GBT PN. Он должен быть уникальным,
  поэтому совпадение почти всегда ошибка ввода;
* **oy_id** — один OY ID использован дважды внутри одной рабочей таблицы.
  Таблицы замен из этой проверки исключены: там несколько аналогов с общим
  OY ID — это норма, а не дубль.

Отчёт читает таблицы целиком, поэтому он не для каждого запроса: вызывать
его стоит по требованию, как ревизию данных.
"""

from collections import Counter

from django.db.models import Q

from .db import unavailable
from .matching import usable
from .registry import CATEGORIES, scan

FIELDS = ("id", "oy_id", "oy_pn", "vendor_pn", "vendor", "gbt_pn", "description")

CHECKS = {
    "vendor": {
        "title": "Один артикул производителя",
        "hint": "Совпадают Vendor PN и Vendor — вероятно, одна деталь заведена дважды",
    },
    "gbt": {
        "title": "Один GBT PN",
        "hint": "Внутренний номер должен быть уникальным",
    },
    "oy_id": {
        "title": "Один OY ID в таблице",
        "hint": "Внутри рабочей таблицы OY ID не должен повторяться; "
                "таблицы замен не проверяются — там общий OY ID это норма",
    },
}
DEFAULT_CHECK = "vendor"


def _key(check, record, category):
    if check == "vendor":
        vendor_pn = usable(record.get("vendor_pn")).lower()
        vendor = usable(record.get("vendor")).lower()
        if vendor_pn and vendor:
            return f"{vendor_pn} · {vendor}"
    elif check == "gbt":
        gbt = usable(record.get("gbt_pn")).lower()
        if gbt:
            return gbt
    elif check == "oy_id":
        if category.replacement:
            return None
        oy_id = usable(record.get("oy_id")).lower()
        if oy_id:
            return f"{category.table} · {oy_id}"
    return None


def find_duplicates(check=DEFAULT_CHECK, term=""):
    """Группы записей с одинаковым ключом. Возвращает (группы, ошибки).

    Проходов по библиотеке два, и это дешевле одного. Первый считает, сколько
    раз встретился каждый ключ, и держит в памяти только сами ключи; второй
    собирает записи, но лишь для ключей, которые повторились. Раньше в память
    попадала вся библиотека целиком — включая подавляющее большинство записей,
    у которых дублей нет и которые в отчёт всё равно не попадут.
    """
    check = check if check in CHECKS else DEFAULT_CHECK
    term = (term or "").strip().lower()

    counts, failed = Counter(), []
    for category, record in scan(FIELDS, failed=failed):
        key = _key(check, record, category)
        if key and (not term or term in key):
            counts[key] += 1

    repeated = {key for key, count in counts.items() if count > 1}
    if not repeated:
        return [], failed

    groups = {}
    for category, record in scan(FIELDS):
        key = _key(check, record, category)
        if key not in repeated:
            continue
        record["category"] = category
        groups.setdefault(key, []).append(record)

    found = [{"key": key, "records": records, "count": len(records),
              "tables": sorted({r["category"].table for r in records})}
             for key, records in groups.items()]
    found.sort(key=lambda group: (-group["count"], group["key"]))
    return found, failed


# --- проверка одной записи при заведении ----------------------------------
#
# Отчёт выше просматривает библиотеку целиком и годится для ревизии данных.
# Здесь другая задача: перед сохранением одной формы быстро выяснить, нет ли
# такого компонента в базе уже. Правила те же самые, чтобы форма и отчёт не
# разошлись, но запросы точечные — по индексируемым полям, а не чтение таблиц.

# сколько найденных записей показывать в предупреждении
MATCH_LIMIT = 5

# по каким полям ищем совпадение: подпись для сообщения и набор полей
MATCH_RULES = (
    ("Vendor PN + Vendor", ("vendor_pn", "vendor")),
    ("GBT PN", ("gbt_pn",)),
)


def _rule_filter(fields, values):
    """Q-условие «все поля правила совпали». None, если нечего сравнивать."""
    query = Q()
    for name in fields:
        value = values.get(name, "")
        if not value:
            # заглушки и пустые значения не опознают компонент: искать по
            # ним значило бы находить всё, у чего поле тоже не заполнено
            return None
        query &= Q(**{f"{name}__iexact": value})
    return query


def find_existing(values, exclude_table=None, exclude_pk=None,
                  limit=MATCH_LIMIT):
    """Записи библиотеки, совпадающие с заводимой по Vendor PN+Vendor или GBT PN.

    ``values`` — словарь значений формы. ``exclude_table``/``exclude_pk``
    исключают саму правимую запись, иначе она нашла бы сама себя.

    Ищет по всем таблицам, включая замены: одна и та же деталь, заведённая
    в двух группах, — такой же дубль, как и внутри одной. Возвращает список
    словарей с записью, её категорией и тем, какое правило сработало.
    """
    cleaned = {name: usable(values.get(name)) for _, fields in MATCH_RULES
               for name in fields}

    rules = [(label, fields, _rule_filter(fields, cleaned))
             for label, fields in MATCH_RULES]
    rules = [(label, fields, q) for label, fields, q in rules if q is not None]
    if not rules:
        return [], []

    found, failed = [], []
    for category in CATEGORIES.values():
        names = category.field_names
        usable_rules = [(label, fields, q) for label, fields, q in rules
                        if all(name in names for name in fields)]
        if not usable_rules:
            continue

        combined = Q()
        for _, _, q in usable_rules:
            combined |= q

        with unavailable(category.table, failed):
            matches = category.model.objects.filter(combined)
            if exclude_table == category.table and exclude_pk is not None:
                matches = matches.exclude(pk=exclude_pk)

            for obj in matches[:limit]:
                found.append({
                    "obj": obj,
                    "category": category,
                    "reason": _matched_rule(obj, usable_rules, cleaned),
                })
        if len(found) >= limit:
            break

    return found[:limit], failed


def _matched_rule(obj, rules, cleaned):
    """Какое из правил сработало на этой записи — для текста предупреждения."""
    for label, fields, _ in rules:
        if all(usable(getattr(obj, name, "")).lower() == cleaned[name].lower()
               for name in fields):
            return label
    return ""
