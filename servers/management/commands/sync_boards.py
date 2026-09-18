"""Заводит позиции для плат.

Платы появляются и мимо импорта — руками, чужими скриптами. Команда
идемпотентна: повторный запуск обновляет, а не плодит.

    python manage.py sync_boards
"""

from django.core.management.base import BaseCommand

from servers.boards_bridge import sync_all


class Command(BaseCommand):
    help = "Создаёт позиции для плат, у которых их ещё нет"

    def handle(self, *args, **options):
        created, updated = sync_all()
        self.stdout.write(self.style.SUCCESS(
            f"позиций заведено: {created}, обновлено: {updated}"))
