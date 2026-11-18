import logging
from datetime import UTC, date, datetime, time

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.models import Company
from apps.core.pagination import StandardPagination
from apps.core.tenancy import tenant_context
from apps.fleet.models import Vehicle

from . import crypto, geometry, services
from .models import Geofence, GeofenceEvent, GpsUnit, WialonAccount
from .wialon import WialonAPIError

logger = logging.getLogger(__name__)


def _perms(view_code: str, manage_code: str, writes=()):
    """Модуль gps включён + право просмотра для чтения и управления для действий-записей."""

    def get_permissions(self):
        write = self.request.method not in ("GET", "HEAD", "OPTIONS") or (
            getattr(self, "action", None) in writes
        )
        return [ModuleRequired("gps")(), permission_required(manage_code if write else view_code)()]

    return get_permissions


# --- аккаунт Wialon -----------------------------------------------------------------------------


class AccountSerializer(serializers.Serializer):
    token = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=True
    )
    base_url = serializers.URLField(required=False)
    is_active = serializers.BooleanField(required=False)


def _account_payload(account: WialonAccount | None, *, webhook: bool = False, request=None) -> dict:
    if account is None:
        return {"configured": False}
    data = {
        "configured": True,
        "has_token": bool(account.token_enc),
        "base_url": account.base_url,
        "is_active": account.is_active,
        "last_synced_at": account.last_synced_at,
        "last_sync_error": account.last_sync_error,
    }
    if webhook and account.webhook_secret and request is not None:
        data["webhook_path"] = (
            f"/api/gps/wialon/webhook/{account.company_id}/{account.webhook_secret}/"
        )
    return data


class AccountView(APIView):
    """Аккаунт Wialon компании: GET (без токена), PUT (пустой токен - без изменения)."""

    get_permissions = _perms("gps.view", "gps.manage")

    def get(self, request):
        account = WialonAccount.objects.first()
        return Response(_account_payload(account, webhook=True, request=request))

    def put(self, request):
        ser = AccountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        account = WialonAccount.objects.first() or WialonAccount()
        if "base_url" in data:
            services.ensure_public_base_url(data["base_url"])
            account.base_url = data["base_url"]
        else:
            services.ensure_public_base_url(account.base_url or "https://hst-api.wialon.com")
        token = (data.get("token") or "").strip()
        if token:
            account.token_enc = crypto.encrypt(token)
        if not account.token_enc:
            raise ValidationError({"token": "Укажите токен Wialon"})
        if "is_active" in data:
            account.is_active = data["is_active"]
        account.save()
        account.ensure_webhook_secret()
        return Response(_account_payload(account, webhook=True, request=request))

    def delete(self, request):
        WialonAccount.objects.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountTestView(APIView):
    """Проверка токена: вход в Wialon без сохранения данных."""

    def get_permissions(self):
        return [ModuleRequired("gps")(), permission_required("gps.manage")()]

    def post(self, request):
        account = WialonAccount.objects.first()
        if account is None or not account.token_enc:
            raise ValidationError({"token": "Сначала сохраните токен Wialon"})
        try:
            client = services.client_for(account)
            info = client.login()
            units = len(client.list_units())
        except WialonAPIError as exc:
            return Response({"ok": False, "error": str(exc)})
        return Response({"ok": True, "user": info.get("au") or "", "units": units})


class SyncView(APIView):
    """Ручная синхронизация: геозоны, юниты, позиции, пробег, топливо."""

    def get_permissions(self):
        return [ModuleRequired("gps")(), permission_required("gps.manage")()]

    def post(self, request):
        account = WialonAccount.objects.first()
        if account is None or not account.token_enc or not account.is_active:
            raise ValidationError({"token": "Аккаунт Wialon не подключён или выключен"})
        try:
            return Response({"ok": True, **services.sync_account(account)})
        except WialonAPIError as exc:
            return Response({"ok": False, "error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


# --- юниты и привязка к технике -------------------------------------------------------------------


class UnitSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.CharField(source="vehicle.plate", read_only=True, default=None)

    class Meta:
        model = GpsUnit
        fields = [
            "id", "unit_id", "name", "vehicle", "vehicle_plate", "lat", "lon", "speed_kmh",
            "position_at", "location_text", "odometer_km", "odometer_at", "fuel_level_l",
            "fuel_level_at", "seen_at",
        ]  # fmt: skip
        read_only_fields = [f for f in fields if f != "vehicle"]


class UnitViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UnitSerializer
    pagination_class = StandardPagination
    get_permissions = _perms("gps.view", "gps.manage", writes=("link", "unlink", "auto_link"))

    def get_queryset(self):
        qs = GpsUnit.objects.select_related("vehicle")
        p = self.request.query_params
        if (p.get("linked") or "") in ("true", "1"):
            qs = qs.filter(vehicle__isnull=False)
        elif (p.get("linked") or "") in ("false", "0"):
            qs = qs.filter(vehicle__isnull=True)
        if q := (p.get("q") or "").strip():
            qs = qs.filter(name__icontains=q)
        return qs

    @action(detail=True, methods=["post"])
    def link(self, request, pk=None):
        """Привязать юнит к технике: {"vehicle": id}. Техника с другим юнитом - 400."""
        unit = self.get_object()
        vehicle_id = request.data.get("vehicle")
        vehicle = Vehicle.objects.filter(pk=vehicle_id).first() if vehicle_id else None
        if vehicle is None:
            raise ValidationError({"vehicle": "Выберите технику"})
        if GpsUnit.objects.filter(vehicle=vehicle).exclude(pk=unit.pk).exists():
            raise ValidationError({"vehicle": "К этой технике уже привязан другой юнит"})
        unit.vehicle = vehicle
        unit.save(update_fields=["vehicle"])
        return Response(UnitSerializer(unit).data)

    @action(detail=True, methods=["post"])
    def unlink(self, request, pk=None):
        unit = self.get_object()
        unit.vehicle = None
        unit.save(update_fields=["vehicle"])
        return Response(UnitSerializer(unit).data)

    @action(detail=False, methods=["post"], url_path="auto-link")
    def auto_link(self, request):
        """Привязать все свободные юниты к технике по госномеру в названии юнита."""
        taken = set(
            GpsUnit.objects.filter(vehicle__isnull=False).values_list("vehicle_id", flat=True)
        )
        free_vehicles = [v for v in Vehicle.objects.all() if v.pk not in taken]
        linked = 0
        for unit in GpsUnit.objects.filter(vehicle__isnull=True):
            match = services.match_vehicle(unit.name, free_vehicles)
            if match is not None:
                unit.vehicle = match
                unit.save(update_fields=["vehicle"])
                free_vehicles.remove(match)
                linked += 1
        return Response({"linked": linked})


# --- геозоны --------------------------------------------------------------------------------------


class GeofenceSerializer(serializers.ModelSerializer):
    polygon = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Geofence
        fields = [
            "id", "name", "kind", "shape", "lat", "lon", "radius_m", "polygon", "is_active",
            "source", "is_approximate", "created_at",
        ]  # fmt: skip
        read_only_fields = ["source", "is_approximate", "created_at"]
        extra_kwargs = {"lat": {"required": False}, "lon": {"required": False}}

    def validate_polygon(self, value):
        if value is None:
            return None
        if (
            not isinstance(value, list)
            or len(value) < 3
            or len(value) > geometry.MAX_POLYGON_POINTS
            or any(not (isinstance(p, (list, tuple)) and len(p) == 2) for p in value)
        ):
            raise serializers.ValidationError("Контур: от 3 точек [широта, долгота]")
        try:
            cleaned = [[float(p[0]), float(p[1])] for p in value]
        except (TypeError, ValueError):
            raise serializers.ValidationError("Координаты должны быть числами") from None
        if any(not (-90 <= a <= 90 and -180 <= b <= 180) for a, b in cleaned):
            raise serializers.ValidationError("Координаты вне допустимых пределов")
        return cleaned

    def validate(self, attrs):
        shape = attrs.get("shape", getattr(self.instance, "shape", Geofence.CIRCLE))
        polygon = attrs.get("polygon", getattr(self.instance, "polygon", None))
        if shape == Geofence.POLYGON:
            if not polygon:
                raise serializers.ValidationError({"polygon": "Для контура нужны точки"})
            lat, lon, radius = geometry.enclosing_circle(polygon)
            attrs["lat"], attrs["lon"], attrs["radius_m"] = round(lat, 6), round(lon, 6), radius
        else:
            attrs["polygon"] = None
            for field in ("lat", "lon"):
                if field not in attrs and not self.instance:
                    raise serializers.ValidationError({field: "Обязательное поле"})
            lat = attrs.get("lat", getattr(self.instance, "lat", None))
            lon = attrs.get("lon", getattr(self.instance, "lon", None))
            if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
                raise serializers.ValidationError({"lat": "Координаты вне допустимых пределов"})
        radius = attrs.get("radius_m") if shape == Geofence.CIRCLE else None
        if radius is not None and not 10 <= radius <= 100_000:
            raise serializers.ValidationError({"radius_m": "Радиус от 10 м до 100 км"})
        return attrs


class GeofenceViewSet(viewsets.ModelViewSet):
    serializer_class = GeofenceSerializer
    pagination_class = StandardPagination
    get_permissions = _perms("gps.view", "gps.manage")

    def get_queryset(self):
        qs = Geofence.objects.all()
        p = self.request.query_params
        if q := (p.get("q") or "").strip():
            qs = qs.filter(name__icontains=q)
        if kind := p.get("kind"):
            qs = qs.filter(kind=kind)
        if (p.get("active") or "") in ("true", "1"):
            qs = qs.filter(is_active=True)
        return qs


class EventSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.CharField(source="vehicle.plate", read_only=True)
    geofence_name = serializers.CharField(source="geofence.name", read_only=True)

    class Meta:
        model = GeofenceEvent
        fields = [
            "id",
            "geofence",
            "geofence_name",
            "vehicle",
            "vehicle_plate",
            "event_type",
            "occurred_at",
        ]


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EventSerializer
    pagination_class = StandardPagination
    get_permissions = _perms("gps.view", "gps.manage")

    def get_queryset(self):
        qs = GeofenceEvent.objects.select_related("vehicle", "geofence")
        p = self.request.query_params
        for field in ("vehicle", "geofence"):
            if value := p.get(field):
                if not value.isdigit():
                    raise ValidationError({field: "Ожидается число"})
                qs = qs.filter(**{f"{field}_id": int(value)})
        if (kind := p.get("event_type")) in ("enter", "exit"):
            qs = qs.filter(event_type=kind)
        return qs


class FuelCheckView(APIView):
    """Заправки по датчику за период и сверка с литрами из отчёта:
    ?vehicle=<id>&date_from=ГГГГ-ММ-ДД&date_to=ГГГГ-ММ-ДД[&reported_l=число]."""

    get_permissions = _perms("gps.view", "gps.manage")

    def get(self, request):
        p = request.query_params
        vehicle = (
            Vehicle.objects.filter(pk=p["vehicle"]).first()
            if (p.get("vehicle") or "").isdigit()
            else None
        )
        if vehicle is None:
            raise ValidationError({"vehicle": "Укажите технику"})
        try:
            first = date.fromisoformat(p.get("date_from", ""))
            last = date.fromisoformat(p.get("date_to", ""))
        except ValueError:
            raise ValidationError({"date_from": "Даты в формате ГГГГ-ММ-ДД"}) from None
        if last < first or (last - first).days > 92:
            raise ValidationError({"date_to": "Период от одного дня до трёх месяцев"})
        reported = p.get("reported_l")
        if reported not in (None, ""):
            try:
                float(reported)
            except ValueError:
                raise ValidationError({"reported_l": "Ожидается число"}) from None
        start = datetime.combine(first, time.min, tzinfo=UTC)
        end = datetime.combine(last, time.max, tzinfo=UTC)
        data = services.fuel_fillings(vehicle, start, end)
        return Response({**data, **services.compare_fuel(reported, data["total_l"])})


# --- вебхук Wialon ("Запрос по URL" в уведомлении) --------------------------------------------


class WebhookThrottle(AnonRateThrottle):
    scope = "gps_webhook"


class WialonWebhookView(APIView):
    """/api/gps/wialon/webhook/<company_id>/<secret>/?event=enter|exit&unit=%UNIT%&zone=%ZONE%

    Секрет в адресе выбирает аккаунт; неверный адрес - обычный 404. Неизвестный юнит или зона -
    ответ 200 с ok=false, чтобы Wialon не повторял запрос бесконечно."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [WebhookThrottle]

    def get(self, request, company_id, secret):
        return self._handle(request, company_id, secret)

    def post(self, request, company_id, secret):
        return self._handle(request, company_id, secret)

    def _handle(self, request, company_id, secret):
        company = Company.objects.filter(pk=company_id).first()
        if company is None:
            raise NotFound()
        with tenant_context(company.pk):
            account = WialonAccount.objects.filter(is_active=True).first()
            if account is None or not services.secret_matches(account, secret):
                raise NotFound()
            params = request.query_params.dict()
            if hasattr(request.data, "items"):
                params.update(
                    {k: v for k, v in request.data.items() if isinstance(v, (str, int, float))}
                )
            event_type = services.webhook_event_type(params.get("event"))
            if event_type is None:
                return Response(
                    {"detail": "event: enter или exit"}, status=status.HTTP_400_BAD_REQUEST
                )
            unit_name = str(params.get("unit", "")).strip()
            zone = str(params.get("zone", "")).strip()
            if not unit_name or not zone:
                return Response(
                    {"detail": "unit и zone обязательны"}, status=status.HTTP_400_BAD_REQUEST
                )
            unit = GpsUnit.objects.filter(name__iexact=unit_name).select_related("vehicle").first()
            vehicle = (
                unit.vehicle
                if unit and unit.vehicle_id
                else services.match_vehicle(unit_name, list(Vehicle.objects.all()))
            )
            if vehicle is None:
                return Response({"ok": False, "reason": "unknown_unit", "unit": unit_name})
            geofences = services.find_geofences_by_name(zone)
            if not geofences:  # зона создана в Wialon только что: обновим список один раз
                try:
                    services.sync_geofences(account)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Wialon webhook: обновление зон: %s", type(exc).__name__)
                geofences = services.find_geofences_by_name(zone)
            if not geofences:
                return Response({"ok": False, "reason": "unknown_zone", "zone": zone})
            when = _event_time(params.get("time"))
            recorded = sum(
                1 for g in geofences if services.record_event(vehicle, g, event_type, when)
            )
            return Response(
                {
                    "ok": True, "vehicle": vehicle.plate, "zones": [g.name for g in geofences],
                    "recorded": recorded, "duplicates": len(geofences) - recorded,
                }
            )  # fmt: skip


def _event_time(raw) -> datetime:
    """Время события из параметра time (unix или ISO); иначе - сейчас."""
    try:
        if raw not in (None, ""):
            text = str(raw).strip()
            if text.replace(".", "", 1).isdigit():
                return datetime.fromtimestamp(float(text), tz=UTC)
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        pass
    return datetime.now(tz=UTC)
