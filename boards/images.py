"""Изображения плат: куда складывать и что с ними делать при загрузке.

Картинки нужны для предпросмотра — посмотреть, как плата выглядит сверху
и снизу. Они есть и у платы, и у ревизии, и это разные снимки: у платы —
общий вид модели, у ревизии — то, как выглядит именно эта ревизия. Ревизии
одной платы различаются посадочными местами и монтажом, поэтому один снимок
на всех был бы неправдой.

Файлы лежат на диске (``MEDIA_ROOT``), в базе — только путь. Раздаёт их
nginx; Django к ним не притрагивается, кроме момента загрузки.
"""

import io
import re

from django.core.exceptions import ValidationError

# Больше этого предпросмотру не нужно: в карточке картинка занимает от силы
# треть экрана, а исходник с телефона приезжает на 12 мегабайт и грузился
# бы при каждом открытии.
MAX_SIDE = 1600
QUALITY = 85

# Предел на приходящий файл. Проверяем до чтения содержимого: смысла
# разбирать двадцатимегабайтный файл, чтобы потом его отклонить, нет.
MAX_BYTES = 12 * 1024 * 1024

# Что принимаем. Формат определяем по содержимому, а не по расширению:
# расширение — это подпись на конверте, её пишет кто угодно.
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def slug(text):
    """Часть пути из номера платы: только то, что безопасно в имени файла."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-") or "board"


def _path(number, filename, side):
    """Путь файла: /pcb/<номер>/<сторона>.<расширение>.

    Имя, с которым файл пришёл, не сохраняем. В нём бывают пробелы,
    кириллица и `IMG_0042.jpg` у трёх плат подряд; Django в таком случае
    дописывает случайный суффикс, и найти потом файл глазами нельзя.
    Номер и сторона однозначны и читаемы.

    Номер платы и номер ревизии не совпадают («HSBP-5S01» против
    «HSBP-5S01-01A»), поэтому снимки платы и её ревизий ложатся в разные
    папки и не затирают друг друга.
    """
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".jpg"
    return f"pcb/{slug(number)}/{side}{suffix}"


def upload_top(instance, filename):
    return _path(instance.base_pn, filename, "top")


def upload_bottom(instance, filename):
    return _path(instance.base_pn, filename, "bottom")


def revision_top(instance, filename):
    return _path(instance.oy_pn, filename, "top")


def revision_bottom(instance, filename):
    return _path(instance.oy_pn, filename, "bottom")


def check(upload):
    """Проверяет загруженный файл. Возвращает формат из содержимого."""
    from PIL import Image, UnidentifiedImageError

    if upload.size > MAX_BYTES:
        raise ValidationError(
            f"Файл больше {MAX_BYTES // 1024 // 1024} МБ — уменьшите его "
            f"перед загрузкой")

    upload.seek(0)
    try:
        image = Image.open(upload)
        image.verify()               # проверка целостности, без распаковки
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError("Это не изображение или файл повреждён") from exc
    finally:
        upload.seek(0)

    if image.format not in FORMATS:
        raise ValidationError(
            "Поддерживаются JPEG, PNG и WebP — пришёл " + (image.format or "?"))
    return image.format


def shrink(upload):
    """Уменьшает картинку до предпросмотра. Возвращает файл для сохранения.

    Оригинал не храним: карточке он не нужен, а место и время загрузки
    занимает. Если понадобится исходник — он есть у того, кто снимал.
    """
    from django.core.files.base import ContentFile
    from PIL import Image, ImageOps

    upload.seek(0)
    image = Image.open(upload)
    # формат запоминаем сразу: после поворота у нового изображения его нет
    fmt = image.format or "JPEG"
    # поворот по EXIF: снимок с телефона иначе ляжет боком
    image = ImageOps.exif_transpose(image)

    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    if fmt == "JPEG" and image.mode not in ("RGB", "L"):
        # JPEG не умеет прозрачность: без перевода Pillow падает
        image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, format=fmt, quality=QUALITY, optimize=True)
    buffer.seek(0)
    return ContentFile(buffer.read())
