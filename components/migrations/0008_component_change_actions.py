from django.db import migrations, models


class Migration(migrations.Migration):
    """Удаление и заведение дубля — такие же события истории, как правка.

    ``choices`` в PostgreSQL ничего не ограничивают: колонка остаётся
    обычной строкой, и миграция меняет только описание поля на стороне
    Django. Данные не трогаются.
    """

    dependencies = [
        ("components", "0007_component_change"),
    ]

    operations = [
        migrations.AlterField(
            model_name="componentchange",
            name="action",
            field=models.CharField(
                choices=[("created", "Заведён"), ("updated", "Изменён"),
                         ("deleted", "Удалён"),
                         ("duplicate", "Заведён как дубль")],
                default="updated", max_length=16,
                verbose_name="Что произошло"),
        ),
    ]
