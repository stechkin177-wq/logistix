from django.apps import AppConfig


class FleetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fleet"
    label = "fleet"

    def ready(self):
        from apps.core import trash

        from .models import Vehicle

        trash.register(Vehicle, "vehicles", "fleet.view")
