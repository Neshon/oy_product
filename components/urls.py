from django.urls import path

from . import link_views, views

app_name = "components"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("search/", views.global_search, name="search"),
    path("duplicates/", views.duplicates, name="duplicates"),
    path("links/import/", link_views.link_import, name="link-import"),
    path("links/add/", link_views.link_add, name="link-add"),
    # история — до маршрута со слагом, иначе «changes» приняли бы за группу
    path("changes/", views.change_log, name="changes"),
    path("changes/<int:pk>/", views.component_change, name="change"),
    path("<slug:slug>/", views.component_list, name="list"),
    path("<slug:slug>/new/", views.ComponentEditView.as_view(), name="create"),
    # ключ строковый: у таблицы Parts роль PK играет текстовый «OY ID»
    path("<slug:slug>/<str:pk>/", views.component_detail, name="detail"),
    path("<slug:slug>/<int:pk>/edit/", views.ComponentEditView.as_view(), name="edit"),
    path("<slug:slug>/<int:pk>/delete/", views.component_delete, name="delete"),
]
