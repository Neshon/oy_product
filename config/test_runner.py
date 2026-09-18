"""Тест-раннер, который заводит таблицы компонентов в тестовой базе.

Зачем. Все 27 таблиц компонентов помечены ``managed = False``: схему ведём
не мы, и миграций у них нет. Django из-за этого не создаёт их и в тестовой
базе — а значит, всё, что работает с компонентами, тестировать нечем.
Отсюда и нынешнее положение дел: тесты в проекте есть, их два десятка, но
все до одного ``SimpleTestCase``, то есть проверяют только то, что
считается в Python. Формы, права, история правок, разузлование и связь
строк BOM с библиотекой не покрыты ничем.

``run_syncdb`` тут не помогает: он создаёт таблицы только для приложений
**без** миграций, а у ``components`` они есть — под конструктор списков и
историю. Поэтому недостающие таблицы создаются здесь явно, схема-редактором.

Подключается в settings:

    TEST_RUNNER = "config.test_runner.UnmanagedModelsRunner"

На боевую базу это не влияет никак: код выполняется только при создании
тестовой.

Важно: таблицы создаются по описанию **моделей**, а не по реальной схеме.
Тест проверяет код, а не то, что колонки названы так же, как в PostgreSQL,
— за это по-прежнему отвечает ``manage.py check_schema`` на живой базе.
"""

from django.apps import apps
from django.db import connections
from django.test.runner import DiscoverRunner


def unmanaged_models():
    """Модели, которых Django сам в тестовой базе не заведёт."""
    return [model for model in apps.get_models() if not model._meta.managed]


class UnmanagedModelsRunner(DiscoverRunner):
    """Обычный раннер плюс создание таблиц неуправляемых моделей."""

    def setup_databases(self, **kwargs):
        config = super().setup_databases(**kwargs)
        for alias in connections:
            self._create_unmanaged(alias)
        return config

    def _create_unmanaged(self, alias):
        connection = connections[alias]
        existing = set(connection.introspection.table_names())
        with connection.schema_editor() as editor:
            for model in unmanaged_models():
                if model._meta.db_table in existing:
                    # таблица уже есть — например, её создала миграция
                    continue
                editor.create_model(model)
