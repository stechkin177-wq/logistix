from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"
    label = "finance"

    def ready(self):
        from apps.core import trash

        from .models import Payment

        trash.register(Payment, "payments", "finance.view")
