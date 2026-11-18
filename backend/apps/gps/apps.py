from django.apps import AppConfig


class GpsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.gps"
    label = "gps"

    def ready(self):
        # источник GPS-пробега для сверки в fleet (fleet.services.mileage_check)
        from apps.fleet.services import register_gps_source

        from .services import gps_mileage_source

        register_gps_source(gps_mileage_source)
