from django.urls import path

from . import views

app_name = "servers"

urlpatterns = [
    path("", views.item_list, name="list"),
    path("new/", views.item_edit, name="create"),
    path("import/", views.bom_import, name="import"),
    path("<int:pk>/", views.item_detail, name="detail"),
    path("<int:pk>/tree/", views.item_tree, name="tree"),
    path("<int:pk>/used/", views.item_where_used, name="where-used"),
    path("<int:pk>/summary/", views.item_summary, name="summary"),
    path("<int:pk>/edit/", views.item_edit, name="edit"),
    path("<int:pk>/delete/", views.item_delete, name="delete"),
    path("<int:pk>/lines/new/", views.line_edit, name="line-create"),
    path("<int:pk>/lines/<int:line_pk>/", views.line_edit, name="line-edit"),
    path("<int:pk>/lines/<int:line_pk>/delete/", views.line_delete,
         name="line-delete"),
]
