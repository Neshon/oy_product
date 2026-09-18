from django.db import migrations


class Migration(migrations.Migration):
    """Удаляет таблицу oy_component_link.

    Ссылка на задачу трекера переехала в колонку «Tracker URL» самих таблиц
    компонентов: у компонента она одна и ведёт себя как обычный параметр —
    её видно в карточке, по ней ищут, её правят руками. Отдельная таблица со
    связью по паре «имя таблицы + ключ» была нужна лишь потому, что колонки
    в исходной схеме не существовало.

    ВАЖНО: до этой миграции выполните
        psql -f sql/add_tracker_url.sql
        psql -f sql/move_component_links.sql
    Первый добавляет колонку, второй переносит накопленные ссылки. Миграция
    удаляет таблицу вместе с данными — после неё переносить будет нечего.
    """

    dependencies = [
        ("components", "0009_change_action_labels"),
    ]

    operations = [
        migrations.DeleteModel(name="ComponentLink"),
    ]
