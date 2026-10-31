from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        from . import rls  # noqa: F401  (синхронизация app.company_id на соединениях)
        from .audit import models as audit_models  # noqa: F401
        from .handbooks import models  # noqa: F401  (регистрация моделей справочников)
        from .numbering import models as numbering_models  # noqa: F401
