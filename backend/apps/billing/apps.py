from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = "apps.billing"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import limits

        limits.connect_signals()  # серверная проверка лимитов тарифа при создании записей
