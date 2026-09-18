from django.urls import path

from . import views

app_name = "boards"

urlpatterns = [
    path("", views.board_list, name="list"),
    path("items/search/", views.item_search, name="item-search"),
    path("import/", views.board_import, name="import"),
    path("new/", views.board_create, name="create"),
    path("<int:pk>/", views.board_detail, name="detail"),
    path("<int:pk>/rev/new/", views.revision_create, name="revision-create"),
    path("<int:pk>/rev/<int:number>/", views.revision_detail, name="revision"),
    path("<int:pk>/rev/<int:number>/edit/", views.revision_edit,
         name="revision-edit"),
    path("<int:pk>/rev/<int:number>/bom/", views.revision_bom, name="bom"),
    path("<int:pk>/rev/<int:number>/checklist/", views.revision_checklist,
         name="checklist"),
    path("<int:pk>/rev/<int:number>/activate/", views.revision_activate,
         name="activate"),
    path("<int:pk>/rev/<int:number>/delete/", views.revision_delete,
         name="revision-delete"),
    path("<int:pk>/edit/", views.board_edit, name="edit"),
    # Строки состава адресуются вместе с ревизией, которой принадлежат.
    # Раньше номера в адресе не было, и правка открывалась у текущей
    # ревизии — какую бы ни смотрели: открыв состав прошлой ревизии и
    # добавив позицию, человек дописывал строку в другую.
    path("<int:pk>/rev/<int:number>/items/pick/", views.item_pick,
         name="item-pick"),
    # Заведение строки: адрес несёт выбранный компонент (?from=&id=), и
    # без него открывать нечего — представление уводит на выбор
    path("<int:pk>/rev/<int:number>/items/new/", views.item_edit,
         name="item-create"),
    path("<int:pk>/rev/<int:number>/items/<int:item_pk>/", views.item_edit,
         name="item-edit"),
    path("<int:pk>/rev/<int:number>/items/<int:item_pk>/delete/",
         views.item_delete, name="item-delete"),
    path("<int:pk>/delete/", views.board_delete, name="delete"),
]
