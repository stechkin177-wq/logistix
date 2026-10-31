from django.apps import AppConfig


class ForwardingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.forwarding"
    label = "forwarding"

    def ready(self):
        from apps.core import trash

        from .models import Carrier, Client, Consignment, Order

        trash.register(Client, "clients", "clients.view")
        trash.register(Carrier, "carriers", "carriers.view")
        trash.register(Order, "orders", "orders.view")
        trash.register(Consignment, "consignments", "consignments.view")
