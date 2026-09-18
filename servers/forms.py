"""Формы раздела серверов: карточка позиции, строка состава, импорт."""

from django import forms

from .models import BomLine, Item


class ItemForm(forms.ModelForm):

    class Meta:
        model = Item
        fields = ("oy_pn", "gct_pn", "name", "kind", "status",
                  "decimal_number", "owner", "description")
        widgets = {
            "oy_pn": forms.TextInput(),
            "gct_pn": forms.TextInput(),
            "name": forms.TextInput(),
            "kind": forms.Select(),
            "status": forms.Select(),
            "decimal_number": forms.TextInput(),
            "owner": forms.TextInput(),
            "description": forms.Textarea(
                attrs={"rows": 5}),
        }

    def clean_oy_pn(self):
        return (self.cleaned_data["oy_pn"] or "").strip()


class BomLineForm(forms.ModelForm):
    """Строка состава.

    Либо вложенная позиция, либо номер и описание — то, чему карточки ещё
    нет. Проверку на кольцо делает сама модель, форме достаточно показать
    её сообщение.
    """

    class Meta:
        model = BomLine
        fields = ("position", "kind", "child", "oy_pn", "gct_pn",
                  "description", "quantity", "unit", "designator", "comment")
        widgets = {
            "position": forms.NumberInput(),
            "kind": forms.Select(),
            "child": forms.Select(),
            "oy_pn": forms.TextInput(),
            "gct_pn": forms.TextInput(),
            "description": forms.Textarea(
                attrs={"rows": 3}),
            "quantity": forms.NumberInput(attrs={"step": "0.001"}),
            "unit": forms.Select(),
            "designator": forms.TextInput(),
            "comment": forms.Textarea(
                attrs={"rows": 3}),
        }

    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_item = parent
        # сама в себя позиция входить не может — и незачем показывать её
        # в списке. Полный список позиций здесь уместен: их сотни, а не
        # десятки тысяч, как компонентов
        children = Item.objects.all()
        if parent is not None:
            children = children.exclude(pk=parent.pk)
        self.fields["child"].queryset = children
        self.fields["child"].required = False
        self.fields["child"].empty_label = "— нет, задаётся номером —"

    def clean(self):
        data = super().clean()
        if self.parent_item is not None:
            self.instance.parent = self.parent_item
        return data


class SystemBomUploadForm(forms.Form):
    file = forms.FileField(
        label="Файл System BOM",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".xlsx,.xlsm"}),
        help_text="Excel с листом «System BOM»: разделы Boards, Cables, "
                  "Mechanics, Other")
    replace = forms.BooleanField(
        required=False, initial=True, label="Заменить прежний импорт",
        help_text="Строки, заведённые руками, остаются на месте в любом случае",
        widget=forms.CheckboxInput(attrs={"class": "checkbox"}))

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith((".xlsx", ".xlsm")):
            raise forms.ValidationError("Нужен файл .xlsx или .xlsm")
        return upload
