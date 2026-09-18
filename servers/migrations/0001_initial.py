"""Позиции и строки состава. Эти таблицы ведёт Django."""

from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        # ссылка на плату: позиция-плата состава не дублирует
        ("boards", "0004_pn_revisions"),
    ]

    operations = [
        migrations.CreateModel(
            name="Item",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("oy_pn", models.CharField(max_length=255, unique=True,
                                           verbose_name="OY P/N")),
                ("gct_pn", models.CharField(blank=True, db_index=True,
                                            default="", max_length=255,
                                            verbose_name="GCT P/N")),
                ("name", models.CharField(blank=True, default="", max_length=255,
                                          verbose_name="Наименование")),
                ("kind", models.CharField(
                    choices=[("server", "Сервер"), ("assembly", "Узел"),
                             ("board", "Плата"), ("cable", "Кабель"),
                             ("chassis", "Корпус"), ("mech", "Механика"),
                             ("material", "Материал"), ("other", "Прочее")],
                    db_index=True, default="assembly", max_length=16,
                    verbose_name="Тип")),
                ("status", models.CharField(
                    choices=[("draft", "В разработке"),
                             ("active", "В производстве"),
                             ("retired", "Снята")],
                    default="draft", max_length=16, verbose_name="Статус")),
                ("decimal_number", models.CharField(
                    blank=True, default="", max_length=128,
                    verbose_name="Децимальный номер")),
                ("description", models.TextField(blank=True, default="",
                                                 verbose_name="Описание")),
                ("owner", models.CharField(blank=True, default="", max_length=150,
                                           verbose_name="Ответственный")),
                ("details", models.JSONField(blank=True, default=dict,
                                             verbose_name="Поля карточки")),
                ("source", models.CharField(blank=True, default="", max_length=255,
                                            verbose_name="Источник")),
                ("created", models.DateTimeField(auto_now_add=True,
                                                 verbose_name="Заведена")),
                ("updated", models.DateTimeField(auto_now=True,
                                                 verbose_name="Изменена")),
                ("board", models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="item", to="boards.board",
                    verbose_name="Плата")),
            ],
            options={
                "ordering": ("kind", "oy_pn"),
                "verbose_name": "Позиция",
                "verbose_name_plural": "Позиции",
            },
        ),
        migrations.CreateModel(
            name="BomLine",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("position", models.IntegerField(blank=True, null=True,
                                                 verbose_name="Позиция в составе")),
                ("kind", models.CharField(
                    choices=[("M", "Основная"), ("S", "Замена")],
                    default="M", max_length=1, verbose_name="Тип строки")),
                ("oy_pn", models.CharField(blank=True, default="", max_length=255,
                                           verbose_name="OY P/N")),
                ("gct_pn", models.CharField(blank=True, default="", max_length=255,
                                            verbose_name="GCT P/N")),
                ("description", models.TextField(blank=True, default="",
                                                 verbose_name="Описание")),
                ("component_table", models.CharField(
                    blank=True, default="", max_length=64,
                    verbose_name="Таблица компонента")),
                ("component_id", models.IntegerField(blank=True, null=True,
                                                     verbose_name="ID компонента")),
                ("quantity", models.DecimalField(
                    decimal_places=3, default=Decimal("1"), max_digits=12,
                    verbose_name="Количество")),
                ("unit", models.CharField(
                    choices=[("шт", "шт"), ("м", "м"), ("мм", "мм"),
                             ("м²", "м²"), ("кг", "кг"), ("г", "г"),
                             ("л", "л"), ("компл", "компл")],
                    default="шт", max_length=8, verbose_name="Ед. изм.")),
                ("designator", models.TextField(blank=True, default="",
                                                verbose_name="Обозначение")),
                ("comment", models.TextField(blank=True, default="",
                                             verbose_name="Примечание")),
                ("source", models.CharField(blank=True, default="", max_length=255,
                                            verbose_name="Источник")),
                ("source_row", models.IntegerField(blank=True, null=True,
                                                   verbose_name="Строка файла")),
                ("child", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="used_in", to="servers.item",
                    verbose_name="Входит")),
                ("parent", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="lines", to="servers.item",
                    verbose_name="Позиция")),
            ],
            options={
                "ordering": ("parent", "position", "kind", "id"),
                "verbose_name": "Строка состава",
                "verbose_name_plural": "Строки состава",
            },
        ),
    ]
