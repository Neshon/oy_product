"""Общая логика для всех моделей компонентов: поиск, фильтры, запись."""

from functools import lru_cache

from django.conf import settings
from django.db import connection, models, transaction
from django.db.models import Max, Q
from django.utils import timezone

from .querystring import values_of

# поля, по которым идёт быстрый поиск в списке и в шапке
SEARCH_FIELDS = (
    "vendor_pn", "oy_pn", "oy_id", "gbt_pn", "description", "vendor",
    "package", "subgroup",
)

# запасной набор фильтров, если категория не задала свой
# (свои наборы — в registry.FILTER_FIELDS)
DEFAULT_FILTER_FIELDS = ("vendor", "subgroup", "smt_tht", "package")


@lru_cache(maxsize=None)
def field_names(model):
    """Имена собственных полей модели.

    Набор полей не меняется за время жизни процесса, а спрашивают о нём
    часто: поиск, фильтры, реестр, отчёт по дублям и построение индексов
    делали это по разу на каждый вызов. Считаем один раз на модель.
    """
    return frozenset(f.name for f in model._meta.fields)


class ComponentQuerySet(models.QuerySet):
    """Поиск и фильтрация, одинаковые для всех групп компонентов."""

    def search(self, term):
        term = (term or "").strip()
        if not term:
            return self
        names = field_names(self.model)
        query = Q()
        for name in SEARCH_FIELDS:
            if name in names:
                query |= Q(**{f"{name}__icontains": term})
        return self.filter(query) if query else self.none()

    def apply_filters(self, params, fields=None):
        """params — QueryDict со значениями фильтров (пустые игнорируются).

        fields — какие поля вообще разрешено фильтровать в этой группе.

        У одного фильтра может быть несколько значений: в строке запроса
        они разделены вертикальной чертой (``?vendor=TDK|Murata``) и
        складываются по «или». Разные фильтры по-прежнему складываются по
        «и». Разбор — в ``querystring.values_of``, он понимает и запись
        повторяющимся параметром.
        """
        names = field_names(self.model)
        queryset = self
        for name in fields or DEFAULT_FILTER_FIELDS:
            if name not in names:
                continue
            values = values_of(params, name)
            if len(values) == 1:
                queryset = queryset.filter(**{name: values[0]})
            elif values:
                queryset = queryset.filter(**{f"{name}__in": values})
        return queryset


class ComponentSaveMixin:
    """Аккуратная запись в неуправляемые (managed=False) таблицы.

    * ``Created`` заполняется при вставке, если его не задали вручную;
    * если в БД у колонки ``id`` нет DEFAULT/IDENTITY, включите
      ``COMPONENTS_ASSIGN_PK_MANUALLY = True`` — тогда следующий id
      вычисляется как ``max(id) + 1`` внутри транзакции.
    """

    def save(self, *args, **kwargs):
        is_new = self._state.adding and self.pk is None

        if is_new and hasattr(self, "created") and self.created is None:
            self.created = timezone.now()

        if is_new and getattr(settings, "COMPONENTS_ASSIGN_PK_MANUALLY", False):
            return self._save_with_manual_pk(*args, **kwargs)

        return super().save(*args, **kwargs)

    def _save_with_manual_pk(self, *args, **kwargs):
        """Вставка с самостоятельно выбранным id.

        Блокировка держится до конца транзакции, поэтому два пользователя
        не получат один и тот же номер.
        """
        table = self._meta.db_table
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))", [table])
            last = type(self).objects.aggregate(value=Max("pk"))["value"]
            self.pk = (last or 0) + 1
            kwargs["force_insert"] = True
            return super().save(*args, **kwargs)
