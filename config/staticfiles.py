"""Статика при разработке: к адресу дописывается время изменения файла.

Зачем. В продакшене имена собранных файлов содержат хэш содержимого
(``CompressedManifestStaticFilesStorage``), поэтому правка CSS меняет адрес
и браузер забирает новый файл сам. При разработке хэша нет: адрес всегда
``/static/components/app.css``, и браузер держит его в кэше.

Ловится это плохо. Страница не падает и ошибок не даёт — она просто
выглядит не так, как её только что поправили, и полчаса уходит на поиск
опечатки в CSS, которого браузер ещё не видел. Новые файлы при этом
подгружаются нормально (их адрес браузер видит впервые), так что симптом
выглядит как «скрипт работает, а стили нет» — и уводит в сторону.

``?v=<время изменения>`` меняет адрес при каждой правке файла и снимает
вопрос. На продакшен это не влияет: там своё хранилище.
"""

import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class VersionedStaticFilesStorage(StaticFilesStorage):
    """``StaticFilesStorage`` плюс метка времени в строке запроса."""

    def url(self, name):
        address = super().url(name)
        stamp = self._modified(name)
        if stamp is None:
            # файла нет среди искателей — например, он пришёл из другого
            # приложения или адрес собран вручную. Отдаём как есть: задача
            # хранилища — найти файл, а не решать за вызывающего
            return address
        separator = "&" if "?" in address else "?"
        return f"{address}{separator}v={stamp}"

    @staticmethod
    def _modified(name):
        found = finders.find(name)
        if not found:
            return None
        if isinstance(found, (list, tuple)):
            found = found[0]
        try:
            return int(os.path.getmtime(found))
        except OSError:
            return None
