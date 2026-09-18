"""Выгрузка состава платы — в CSV и в Excel.

И то, и другое отдаёт **снимок файла**: состав показывается и выгружается
таким, каким его импортировали, без подстановки значений из библиотеки.
Спецификация — документ, и экспорт должен совпадать с тем, что загрузили.

Собран отдельно от представлений: выбор формата — это одна строка в
``boards.views``, а правила самой выгрузки живут здесь.
"""

from django.utils.text import slugify

from components.export import csv_response, export_stamp

from .excel import build_workbook, workbook_response

# колонки выгрузки: имя поля и заголовок, как в исходном BOM
CSV_COLUMNS = (
    ("position", "I/N"), ("kind", "M/S"), ("vendor_pn", "Vendor P/N"),
    ("vendor", "Vendor"), ("country", "Country"), ("oy_id", "OY ID"),
    ("oy_pn", "OY P/N"), ("gbt_pn", "GBT P/N"), ("group", "Group"),
    ("subgroup", "Subgroup"), ("description", "Description"),
    ("description_gbt", "Description GBT"), ("smt_tht", "SMT/THT"),
    ("references", "Part References"), ("qty", "QTY"), ("comment", "Comment"),
)


def _filename(board, revision, extension):
    return f"{slugify(revision.oy_pn or board.base_pn) or 'bom'}-rev{revision.number}.{extension}"


def export_csv(board, revision, items, username=""):
    """CSV с отметкой о выгрузке в первых строках.

    Отметка стоит перед таблицей, как шапка в Excel-выгрузке: файл уходит
    в переписку, и по нему должно быть видно, кто и когда его достал.

    Из-за неё заголовок колонок — не первая строка файла, а третья. Excel и
    LibreOffice это переживают, а тому, кто читает CSV программой, нужен
    пропуск двух строк. Другого места для отметки в CSV нет: в самой
    таблице для неё нет колонки, а в конце файла её не заметят.
    """
    rows = ([item.export_value(name) for name, _ in CSV_COLUMNS]
            for item in items)
    return csv_response(_filename(board, revision, "csv"),
                        [label for _, label in CSV_COLUMNS], rows,
                        preamble=export_stamp(username))


def export_xlsx(board, revision, items, username=""):
    """Excel в том же виде, в каком BOM приходят к нам.

    Такой файл читается обратно нашим же импортом, поэтому его можно
    править в Excel и загружать следующей ревизией.

    В шапку дописывается отметка о выгрузке — кто и когда. Файл уходит из
    библиотеки в переписку и на диск R, и через месяц по нему уже не
    понять, из какого он состояния базы; отметка отвечает на этот вопрос,
    не выдавая себя за дату и автора самого BOM
    (см. components.export.EXPORT_LABELS).
    """
    return workbook_response(_filename(board, revision, "xlsx"),
                             build_workbook(revision, items,
                                            exported_by=username))


# что понимает параметр ?export=
FORMATS = {"csv": export_csv, "xlsx": export_xlsx}


def exporter(name):
    """Функция выгрузки по имени формата или None, если формат не наш."""
    return FORMATS.get(name)
