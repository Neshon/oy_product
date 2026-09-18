from django.apps import AppConfig


class ComponentsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "components"
    verbose_name = "Справочник компонентов"

    def ready(self):
        """Подписывается на изменения, от которых устаревает кэш.

        Кэшируются значения фильтров, счётчики главной и справочник
        выпадающих списков (см. ``components.cache``). Срок жизни у них
        есть, но ждать его после собственной же правки незачем: завели
        компонент — счётчик должен измениться сразу, а не через пять минут.
        """
        from django.db.models.signals import post_delete, post_save

        from . import cache as component_cache
        from .models import OptionField, OptionValue
        from .registry import CATEGORIES

        def forget_table(sender, **kwargs):
            component_cache.drop_table(sender._meta.db_table)

        def forget_options(sender, **kwargs):
            component_cache.drop_options()

        # ссылку на приёмники держим на самом AppConfig: сигналы Django
        # хранят их слабой ссылкой, и без этого локальные функции пропали
        # бы сразу после выхода из ready()
        self._cache_receivers = (forget_table, forget_options)

        for category in CATEGORIES.values():
            post_save.connect(forget_table, sender=category.model,
                              dispatch_uid=f"forget-save:{category.table}")
            post_delete.connect(forget_table, sender=category.model,
                                dispatch_uid=f"forget-delete:{category.table}")

        for model in (OptionField, OptionValue):
            post_save.connect(
                forget_options, sender=model,
                dispatch_uid=f"forget-options-save:{model.__name__}")
            post_delete.connect(
                forget_options, sender=model,
                dispatch_uid=f"forget-options-delete:{model.__name__}")
