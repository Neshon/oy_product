"""Ещё три папки на диске R и формат файла у строки чек-листа.

На страницах ревизий ссылок оказалось больше, чем в шаблоне: кроме
Manufacture и Assembly встречаются Source, Testing и ЕСКД. А в чек-листах
рядом с документом указан его формат (*.xlsx, *.step, «Ссылка на
Confluence») — это часть ответа, а не украшение: по нему видно, ждут файл
или ссылку.
"""

from django.db import migrations, models

REVISION = [
    ("source_dir_url", "Папка Source (диск R)"),
    ("testing_dir_url", "Папка Testing (диск R)"),
    ("eskd_dir_url", "Папка ЕСКД (диск R)"),
]


class Migration(migrations.Migration):

    dependencies = [("boards", "0007_checklists")]

    operations = [
        migrations.AddField(
            "boardrevision", name,
            models.CharField(blank=True, default="", max_length=500,
                             verbose_name=verbose))
        for name, verbose in REVISION
    ] + [
        migrations.AddField(
            "checklistitem", "file_format",
            models.CharField(blank=True, default="", max_length=64,
                             verbose_name="Формат файла")),
    ]
