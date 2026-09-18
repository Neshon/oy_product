"""Выгрузка таблиц в CSV.

Один помощник на оба раздела: и список компонентов, и состав платы
отдаются в одинаковом виде — точка с запятой как разделитель и BOM в
начале файла, иначе Excel открывает кириллицу «кракозябрами».
"""

import csv

from django.http import HttpResponse
from django.utils import timezone

DELIMITER = ";"
BOM = "\ufeff"

# Отметка о выгрузке: кто и когда достал файл из библиотеки.
#
# Подписи намеренно не «Date» и «Author»: так в присланных BOM подписаны
# дата и автор самого состава, а это наша отметка — она говорит, когда файл
# достали, а не когда его составили. Совпади подписи, через две пересылки
# одно начало бы выдавать себя за другое.
#
# Лежат здесь, а не в boards: один и тот же файл приходит то в CSV, то в
# Excel, из раздела плат или из списка компонентов, — и называться отметка
# должна одинаково везде.
EXPORT_LABELS = ("Exported", "Exported by")
EXPORT_TIME_FORMAT = "%d.%m.%Y %H:%M"


def export_stamp(username, when=None):
    """Две строки отметки — для preamble в CSV и для шапки в Excel."""
    moment = (when or timezone.localtime()).strftime(EXPORT_TIME_FORMAT)
    return [[EXPORT_LABELS[0], moment], [EXPORT_LABELS[1], username or ""]]


def csv_response(filename, headers, rows, preamble=()):
    """Отдаёт CSV на скачивание.

    ``rows`` — любой итератор списков значений; ``None`` пишется пустой
    ячейкой. Строки не собираются в память целиком, поэтому выгрузка
    большой таблицы не зависит от её размера.

    ``preamble`` — строки перед заголовком таблицы: отметка о выгрузке и
    тому подобное. За ней ставится пустая строка — так Excel видит, где
    кончается шапка и начинается таблица.

    Осторожно: с непустой ``preamble`` заголовок перестаёт быть первой
    строкой файла. Для тех, кто читает CSV программой, это значимо
    (``skiprows``), поэтому передавайте её только там, где знаете, кто
    файл открывает.
    """
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(BOM)
    writer = csv.writer(response, delimiter=DELIMITER)

    for line in preamble:
        writer.writerow(line)
    if preamble:
        writer.writerow([])

    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return response
