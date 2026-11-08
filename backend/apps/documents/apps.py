from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.documents"
    label = "documents"

    def ready(self):
        from .builtin import register_builtin_providers

        register_builtin_providers()  # семь прежних видов - встроенными поставщиками

        from apps.core.signals import company_created

        from .starter import seed_starter_templates

        def on_company_created(sender, company, **kwargs):
            seed_starter_templates(company)

        company_created.connect(
            on_company_created, dispatch_uid="documents.seed_starter_templates", weak=False
        )
