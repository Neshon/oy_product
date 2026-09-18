"""Таблицы плат и составов. Их создаёт Django: в исходной схеме их нет."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Board",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("oy_pn", models.CharField(max_length=128, unique=True,
                                           verbose_name="OY P/N")),
                ("gct_pn", models.CharField(blank=True, default="", max_length=128,
                                            verbose_name="GCT P/N")),
                ("old_oy_pn", models.CharField(blank=True, default="", max_length=128,
                                               verbose_name="Старый OY P/N")),
                ("old_gct_pn", models.CharField(blank=True, default="", max_length=128,
                                                verbose_name="Старый GCT P/N")),
                ("decimal_number", models.CharField(blank=True, default="",
                                                    max_length=128,
                                                    verbose_name="Децимальный номер")),
                ("bom_date", models.CharField(blank=True, default="", max_length=64,
                                              verbose_name="Дата BOM")),
                ("author", models.CharField(blank=True, default="", max_length=255,
                                            verbose_name="Автор")),
                ("source_file", models.CharField(blank=True, default="", max_length=255,
                                                 verbose_name="Файл")),
                ("imported_at", models.DateTimeField(auto_now=True,
                                                     verbose_name="Импортировано")),
                ("imported_by", models.CharField(blank=True, default="", max_length=150,
                                                 verbose_name="Кто импортировал")),
            ],
            options={
                "ordering": ("oy_pn",),
                "verbose_name": "Плата",
                "verbose_name_plural": "Платы",
            },
        ),
        migrations.CreateModel(
            name="BoardItem",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("position", models.IntegerField(blank=True, null=True,
                                                 verbose_name="Позиция")),
                ("kind", models.CharField(
                    choices=[("M", "Основной"), ("S", "Замена")], default="M",
                    max_length=1, verbose_name="Тип строки")),
                ("vendor_pn", models.CharField(blank=True, default="", max_length=255,
                                               verbose_name="Vendor P/N")),
                ("vendor", models.CharField(blank=True, default="", max_length=255,
                                            verbose_name="Vendor")),
                ("country", models.CharField(blank=True, default="", max_length=128,
                                             verbose_name="Country")),
                ("oy_id", models.CharField(blank=True, default="", max_length=128,
                                           verbose_name="OY ID")),
                ("oy_pn", models.CharField(blank=True, default="", max_length=255,
                                           verbose_name="OY P/N")),
                ("gbt_pn", models.CharField(blank=True, default="", max_length=255,
                                            verbose_name="GBT P/N")),
                ("group", models.CharField(blank=True, default="", max_length=128,
                                           verbose_name="Group")),
                ("subgroup", models.CharField(blank=True, default="", max_length=128,
                                              verbose_name="Subgroup")),
                ("description", models.TextField(blank=True, default="",
                                                 verbose_name="Description")),
                ("description_gbt", models.TextField(blank=True, default="",
                                                     verbose_name="Description GBT")),
                ("smt_tht", models.CharField(blank=True, default="", max_length=32,
                                             verbose_name="SMT/THT")),
                ("references", models.TextField(blank=True, default="",
                                                verbose_name="Part References")),
                ("qty", models.IntegerField(blank=True, null=True, verbose_name="QTY")),
                ("comment", models.TextField(blank=True, default="",
                                             verbose_name="Comment")),
                ("row", models.IntegerField(blank=True, null=True,
                                            verbose_name="Строка файла")),
                ("board", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="items", to="boards.board", verbose_name="Плата")),
            ],
            options={
                "ordering": ("board", "position", "kind", "id"),
                "verbose_name": "Строка состава",
                "verbose_name_plural": "Состав платы",
            },
        ),
        migrations.AddIndex(
            model_name="boarditem",
            index=models.Index(fields=["vendor_pn"], name="boarditem_vendor_pn_idx"),
        ),
        migrations.AddIndex(
            model_name="boarditem",
            index=models.Index(fields=["gbt_pn"], name="boarditem_gbt_pn_idx"),
        ),
        migrations.AddIndex(
            model_name="boarditem",
            index=models.Index(fields=["oy_id"], name="boarditem_oy_id_idx"),
        ),
    ]
