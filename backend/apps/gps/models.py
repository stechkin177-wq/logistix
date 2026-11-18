"""Модуль gps: аккаунт Wialon компании, юниты (снимок и привязка к технике), геозоны, события.

GPS не меняет официальный пробег техники и не привязывается к рейсу автоматически (решения
заказчика);
пробег по GPS только показывается для сверки (fleet.services.mileage_check)."""

import secrets

from django.db import models
from django.db.models import Q

from apps.core.models import TenantModel


class WialonAccount(TenantModel):
    """Токен Wialon компании (один на компанию). Хранится зашифрованным и наружу не отдаётся."""

    token_enc = models.TextField(blank=True)
    base_url = models.URLField(default="https://hst-api.wialon.com")
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True)
    # Секрет в адресе вебхука Wialon (въезд/выезд из зон): случайный, виден только администратору.
    webhook_secret = models.CharField(max_length=64, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company"], name="wialonaccount_company_uniq"),
        ]

    def ensure_webhook_secret(self, rotate: bool = False) -> str:
        if rotate or not self.webhook_secret:
            self.webhook_secret = secrets.token_urlsafe(24)
            self.save(update_fields=["webhook_secret"])
        return self.webhook_secret


class GpsUnit(TenantModel):
    """Юнит Wialon: снимок (позиция, пробег, топливо) и необязательная привязка к технике."""

    unit_id = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    vehicle = models.ForeignKey(
        "fleet.Vehicle", null=True, blank=True, on_delete=models.SET_NULL, related_name="gps_units"
    )
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    speed_kmh = models.PositiveIntegerField(null=True, blank=True)
    position_at = models.DateTimeField(null=True, blank=True)
    location_text = models.CharField(max_length=500, blank=True)
    odometer_km = models.DecimalField(max_digits=11, decimal_places=1, null=True, blank=True)
    odometer_at = models.DateTimeField(null=True, blank=True)
    fuel_level_l = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    fuel_level_at = models.DateTimeField(null=True, blank=True)
    seen_at = models.DateTimeField(
        null=True, blank=True
    )  # когда юнит последний раз был в ответе Wialon

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "unit_id"], name="gpsunit_company_unit_uniq"
            ),
            models.UniqueConstraint(
                fields=["company", "vehicle"],
                condition=Q(vehicle__isnull=False),
                name="gpsunit_company_vehicle_uniq",
            ),
        ]

    def __str__(self):
        return self.name


class Geofence(TenantModel):
    """Геозона: круг или контур (полигон). Контур хранится точками [lat, lon]; для карты у него
    есть описывающий круг (lat, lon, radius_m)."""

    WAREHOUSE = "warehouse"
    BORDER = "border"
    CITY = "city"
    CLIENT = "client"
    OTHER = "other"
    KINDS = [
        (WAREHOUSE, "Склад"), (BORDER, "Погранпереход"), (CITY, "Город"),
        (CLIENT, "Клиент"), (OTHER, "Прочее"),
    ]  # fmt: skip
    CIRCLE = "circle"
    POLYGON = "polygon"
    SHAPES = [(CIRCLE, "Круг"), (POLYGON, "Контур")]
    MANUAL = "manual"
    WIALON = "wialon"
    SOURCES = [(MANUAL, "Вручную"), (WIALON, "Wialon")]

    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=12, choices=KINDS, default=OTHER)
    shape = models.CharField(max_length=8, choices=SHAPES, default=CIRCLE)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lon = models.DecimalField(max_digits=9, decimal_places=6)
    radius_m = models.PositiveIntegerField(default=500)
    polygon = models.JSONField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    source = models.CharField(max_length=8, choices=SOURCES, default=MANUAL)
    wialon_resource_id = models.CharField(max_length=32, blank=True, default="")
    wialon_zone_id = models.CharField(max_length=32, blank=True, default="")
    is_approximate = models.BooleanField(default=False)  # линия Wialon заменена кругом
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "wialon_resource_id", "wialon_zone_id"],
                condition=~Q(wialon_zone_id=""),
                name="geofence_company_wialon_zone_uniq",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["warehouse", "border", "city", "client", "other"]),
                name="geofence_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(shape__in=["circle", "polygon"]), name="geofence_shape_valid"
            ),
        ]

    def __str__(self):
        return self.name


class VehicleGeofenceState(TenantModel):
    """Внутри ли техника зоны по последней проверке: событие пишется только при смене состояния."""

    vehicle = models.ForeignKey(
        "fleet.Vehicle", on_delete=models.CASCADE, related_name="geofence_states"
    )
    geofence = models.ForeignKey(Geofence, on_delete=models.CASCADE, related_name="vehicle_states")
    is_inside = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "vehicle", "geofence"], name="geostate_company_veh_geo_uniq"
            )
        ]


class GeofenceEvent(TenantModel):
    """Въезд или выезд, записанный проверкой позиции или вебхуком Wialon."""

    ENTER = "enter"
    EXIT = "exit"
    TYPES = [(ENTER, "Въезд"), (EXIT, "Выезд")]

    geofence = models.ForeignKey(Geofence, on_delete=models.CASCADE, related_name="events")
    vehicle = models.ForeignKey(
        "fleet.Vehicle", on_delete=models.CASCADE, related_name="geofence_events"
    )
    event_type = models.CharField(max_length=5, choices=TYPES)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(
                fields=["company", "vehicle", "-occurred_at"], name="geoevent_veh_time_idx"
            ),
            models.Index(
                fields=["company", "geofence", "-occurred_at"], name="geoevent_geo_time_idx"
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(event_type__in=["enter", "exit"]), name="geoevent_type_valid"
            )
        ]
