"""Ссылка на компонент парой «имя таблицы + ключ записи».

Внешнего ключа тут быть не может: таблиц компонентов 27 и они неуправляемые.
Поэтому на компонент ссылаются двумя колонками, и так устроены обе ссылающиеся
модели — строка состава платы (:class:`boards.models.BoardItem`) и запись
истории (:class:`components.models.ComponentChange`).

Сами колонки у них объявлены по-своему и здесь не описаны — у строки состава
ключ необязательный (компонента в библиотеке может не найтись), у записи
истории обязательный. Сводить их в абстрактную модель значило бы менять
схему ради красоты. Общее здесь другое и более важное — **что делать с этой
парой**: как достать категорию, как достать саму запись, как собрать ссылку
на карточку и что показывать, когда компонент уже удалили.

Раньше эти четыре шага были написаны заново в карточке правки, в импорте
ссылок, в поиске применений и в команде пересчёта связей — и обрабатывали
«записи больше нет» каждый по-своему.

Отдельно стоит помнить, чего этот модуль **не** делает: он не подставляет
значения из библиотеки в строку состава. Спецификация — документ, и
показывается она так, как записана в файле; ссылка ведёт на карточку, где
видно, что в библиотеке сейчас.
"""

from django.urls import reverse

from .db import fallback

# Реестр импортируется внутри функций, а не здесь. Причина — кольцо:
# models.py подмешивает ComponentRefMixin, то есть грузит этот модуль; а
# registry.py строит категории по моделям, то есть грузит models.py. При
# импорте наверху Python упёрся бы в полузагруженный модуль. Тот же приём
# был и раньше, в BoardItem.library_url.


def component_url(table, pk):
    """Адрес карточки компонента или пустая строка.

    Запрос к базе не делается: адрес собирается из имени таблицы и ключа,
    записанных при импорте. Поэтому показ состава платы не стоит ни одного
    обращения к таблицам компонентов, сколько бы строк в нём ни было.
    """
    from .registry import category_by_table

    if not table or pk is None:
        return ""
    category = category_by_table(table)
    if category is None:
        return ""
    return reverse("components:detail", args=[category.slug, pk])


@fallback(None, "чтение компонента по ссылке «таблица + ключ»")
def component_object(table, pk):
    """Сама запись или ``None``.

    ``None`` — законный ответ, а не сбой: компонент могли удалить, а
    ссылающаяся строка остаётся. История правок это переживает намеренно —
    «кто и когда трогал» бывает нужно как раз после удаления.
    """
    from .registry import category_by_table

    category = category_by_table(table)
    if category is None or pk is None:
        return None
    return category.model.objects.filter(pk=pk).first()


def resolve(table, pk):
    """``(категория, запись)``. Любое из двух может быть ``None``.

    Категория без записи значит «таблица та, а записи уже нет»: на странице
    это разные сообщения — «неизвестная таблица» и «компонент удалён».
    """
    from .registry import category_by_table

    category = category_by_table(table)
    if category is None:
        return None, None
    return category, component_object(table, pk)


class ComponentRefMixin:
    """Поведение пары «component_table + component_id».

    Полей не объявляет: их описывает сама модель, у каждой по-своему.
    Подмешивается перед ``models.Model``::

        class BoardItem(ComponentRefMixin, models.Model):
            ...
    """

    @property
    def is_linked(self):
        return self.component_id is not None

    @property
    def component_url(self):
        """Ссылка на карточку связанного компонента; без связи — пусто."""
        return component_url(self.component_table, self.component_id)

    @property
    def component_category(self):
        from .registry import category_by_table

        return category_by_table(self.component_table)

    def component(self):
        """Связанная запись или ``None``, если её уже нет.

        Метод, а не свойство: это запрос к базе, и из шаблона его дёргать
        не следует — в списке это был бы запрос на строку.
        """
        return component_object(self.component_table, self.component_id)
