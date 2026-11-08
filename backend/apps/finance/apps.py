from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"
    label = "finance"

    def ready(self):
        from apps.core import trash

        from .models import Payment

        trash.register(Payment, "payments", "finance.view")

        from apps.core.signals import company_created

        from .initial_settings import on_company_created

        company_created.connect(
            on_company_created, dispatch_uid="finance_company_financial_settings"
        )

        from apps.core.module_services import register_disable_guard

        from .module_guard import finance_disable_guard

        register_disable_guard("finance", finance_disable_guard)
