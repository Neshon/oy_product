from django.db import migrations, models


class Migration(migrations.Migration):
    """«Заведён» → «Добавлен» в подписях действий.

    Меняются только подписи, не значения: в базе по-прежнему лежат
    ``created``, ``updated``, ``deleted``, ``duplicate``. Данные не
    трогаются, миграция нужна лишь для того, чтобы ``makemigrations``
    не считал модель разошедшейся с историей миграций.
    """

    dependencies = [
        ("components", "0008_component_change_actions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="componentchange",
            name="action",
            field=models.CharField(
                choices=[("created", "Добавлен"), ("updated", "Изменён"),
                         ("deleted", "Удалён"),
                         ("duplicate", "Добавлен как дубль")],
                default="updated", max_length=16,
                verbose_name="Что произошло"),
        ),
    ]
