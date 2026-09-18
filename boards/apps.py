from django.apps import AppConfig


class BoardsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "boards"
    verbose_name = "Платы и BOM"

    def ready(self):
        """Сбрасывает показатель по составам, когда состав меняется.

        ``bom_coverage`` считается по всем строкам текущих ревизий и висит
        на главной, поэтому кэшируется. Импорт BOM, смена текущей ревизии и
        правка позиции руками должны быть видны сразу, а не через срок
        жизни кэша.
        """
        from django.db.models.signals import post_delete, post_save

        from components.cache import COVERAGE_KEY, drop

        from .models import Board, BoardItem, BoardRevision

        def forget_coverage(sender, **kwargs):
            drop(COVERAGE_KEY)

        # сигналы держат приёмник слабой ссылкой — сохраняем её на AppConfig
        self._cache_receiver = forget_coverage

        for model in (Board, BoardRevision, BoardItem):
            post_save.connect(forget_coverage, sender=model,
                              dispatch_uid=f"coverage-save:{model.__name__}")
            post_delete.connect(forget_coverage, sender=model,
                                dispatch_uid=f"coverage-delete:{model.__name__}")
