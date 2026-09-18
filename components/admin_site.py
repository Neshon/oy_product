"""Своя админка: конструктор списков вынесен отдельным блоком.

Среди 27 таблиц компонентов «Столбцы со списками» терялись, поэтому на
главной странице админки они показываются своим разделом. Отдельное
приложение ради одной модели заводить незачем — достаточно переложить её
в свой раздел списка.

Раньше то же самое делалось подменой ``admin.site.get_app_list`` на лету.
Замена метода у чужого объекта переживает не каждое обновление Django,
а штатный способ — свой класс сайта, объявленный в ``AdminConfig``.
"""

from django.contrib.admin import AdminSite

SECTION_TITLE = "Конструктор выпадающих списков"
SECTION_MODELS = {"OptionField"}


class ComponentsAdminSite(AdminSite):
    site_header = "Библиотека компонентов"
    site_title = "Библиотека компонентов"
    index_title = "Компоненты и параметры"

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        moved, source = [], None

        for app in app_list:
            for model in list(app.get("models", [])):
                if model.get("object_name") in SECTION_MODELS:
                    app["models"].remove(model)
                    moved.append(model)
                    source = app

        if moved and source:
            app_list.append({
                "name": SECTION_TITLE,
                "app_label": source["app_label"],
                "app_url": source["app_url"],
                "has_module_perms": source.get("has_module_perms", True),
                "models": moved,
            })
        return [app for app in app_list if app.get("models")]
