"""Подключение своей админки — отдельным модулем, и на то две причины.

Первая: в ``apps.py`` этому классу не место. Django ищет там AppConfig по
умолчанию для приложения ``components`` и считает кандидатами все классы
модуля, включая импортированный ``AdminConfig``. У него и у наследника
``default = True``, и приложение перестаёт загружаться с ошибкой
«declares more than one default AppConfig».

Вторая: этот модуль читается до того, как загрузятся модели, поэтому
импортировать здесь можно только ``django.contrib.admin.apps`` — сам
``django.contrib.admin`` тянет за собой модель LogEntry и падает с
AppRegistryNotReady. По той же причине сайт указан строкой, а не
импортом: её разбирают уже в ``ready()``.
"""

from django.contrib.admin.apps import AdminConfig


class ComponentsAdminConfig(AdminConfig):
    """Ставит ComponentsAdminSite на место стандартного admin.site."""

    default_site = "components.admin_site.ComponentsAdminSite"
