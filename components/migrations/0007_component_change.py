from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0006_component_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="ComponentChange",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("component_table", models.CharField(
                    max_length=64, verbose_name="Таблица компонента")),
                ("component_id", models.IntegerField(
                    verbose_name="Ключ компонента")),
                ("author", models.CharField(blank=True, default="",
                                            max_length=150,
                                            verbose_name="Кто")),
                ("created", models.DateTimeField(auto_now_add=True,
                                                 verbose_name="Когда")),
                ("action", models.CharField(
                    choices=[("created", "Заведён"), ("updated", "Изменён")],
                    default="updated", max_length=16,
                    verbose_name="Что произошло")),
                ("source", models.CharField(
                    blank=True, default="",
                    help_text="Через сайт или через админку",
                    max_length=32, verbose_name="Откуда")),
                ("changes", models.JSONField(
                    blank=True, default=list,
                    help_text="Список полей: имя, подпись, старое значение, новое",
                    verbose_name="Что поменялось")),
            ],
            options={
                "db_table": "oy_component_change",
                "ordering": ("-created", "-id"),
                "verbose_name": "Изменение компонента",
                "verbose_name_plural": "История изменений",
            },
        ),
        migrations.AddIndex(
            model_name="componentchange",
            index=models.Index(
                fields=["component_table", "component_id", "-created"],
                name="component_change_target_idx"),
        ),
    ]
