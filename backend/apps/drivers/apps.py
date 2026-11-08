from django.apps import AppConfig


class DriversConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.drivers"
    label = "drivers"

    def ready(self):
        from apps.core import trash

        from .models import Driver

        trash.register(Driver, "drivers", "drivers.view")
