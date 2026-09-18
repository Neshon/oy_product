from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0005_rename_option_field"),
    ]

    operations = [
        migrations.CreateModel(
            name="ComponentLink",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("component_table", models.CharField(
                    max_length=64, verbose_name="Таблица компонента")),
                ("component_id", models.IntegerField(
                    verbose_name="Ключ компонента")),
                ("url", models.URLField(max_length=500, verbose_name="Ссылка")),
                ("title", models.CharField(blank=True, default="",
                                           max_length=255,
                                           verbose_name="Название")),
                ("source", models.CharField(
                    blank=True, default="",
                    help_text="Откуда ссылка: имя импорта или «вручную»",
                    max_length=64, verbose_name="Источник")),
                ("matched_by", models.CharField(blank=True, default="",
                                                max_length=32,
                                                verbose_name="Сопоставлено по")),
                ("created", models.DateTimeField(auto_now_add=True,
                                                 verbose_name="Добавлена")),
            ],
            options={
                "db_table": "oy_component_link",
                "ordering": ("component_table", "component_id", "id"),
                "verbose_name": "Ссылка на компонент",
                "verbose_name_plural": "Ссылки на компоненты",
            },
        ),
        migrations.AddIndex(
            model_name="componentlink",
            index=models.Index(fields=["component_table", "component_id"],
                               name="component_link_target_idx"),
        ),
        migrations.AddConstraint(
            model_name="componentlink",
            constraint=models.UniqueConstraint(
                fields=("component_table", "component_id", "url"),
                name="component_link_unique"),
        ),
    ]
