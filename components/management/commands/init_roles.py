"""Создаёт роли-группы и, по желанию, назначает их пользователям.

    python manage.py init_roles
    python manage.py init_roles --assign ivanov=Библиотекари --assign petrov=Схемотехники
    python manage.py init_roles --list

Права раздаёт не Django-механизм разрешений, а членство в группе:
таблицы компонентов неуправляемые, и стандартные права на них мало что
значат. Проверки собраны в components/permissions.py.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from components.permissions import ROLES


class Command(BaseCommand):
    help = "Создаёт роли «Схемотехники», «Топологи», «Библиотекари»"

    def add_arguments(self, parser):
        parser.add_argument("--assign", action="append", dest="assign",
                            metavar="ЛОГИН=РОЛЬ",
                            help="назначить роль пользователю")
        parser.add_argument("--list", action="store_true",
                            help="показать роли и их состав")

    def handle(self, *args, **options):
        for name, description in ROLES.items():
            _, created = Group.objects.get_or_create(name=name)
            mark = "создана" if created else "уже есть"
            self.stdout.write(f"{name}: {mark} — {description}")

        for pair in options["assign"] or []:
            if "=" not in pair:
                raise CommandError(f"Ожидается ЛОГИН=РОЛЬ, получено: {pair}")
            username, role = (part.strip() for part in pair.split("=", 1))
            if role not in ROLES:
                raise CommandError(
                    f"Неизвестная роль «{role}». Доступны: "
                    + ", ".join(ROLES))
            user = get_user_model().objects.filter(username=username).first()
            if user is None:
                raise CommandError(f"Пользователь «{username}» не найден")
            user.groups.add(Group.objects.get(name=role))
            self.stdout.write(self.style.SUCCESS(
                f"{username} → {role}"))

        if options["list"]:
            self.stdout.write("")
            for name in ROLES:
                members = (get_user_model().objects
                           .filter(groups__name=name)
                           .values_list("username", flat=True))
                self.stdout.write(
                    f"{name}: " + (", ".join(members) or "никого"))
            admins = (get_user_model().objects.filter(is_superuser=True)
                      .values_list("username", flat=True))
            self.stdout.write("Администраторы: " + (", ".join(admins) or "никого"))
