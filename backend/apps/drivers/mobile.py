"""Мобильная версия водителя (модуль driver_app): «я», мои рейсы, карточка рейса, действия.

Изоляция: водитель видит ТОЛЬКО рейсы, где Trip.driver - его карточка (Driver.user = он сам);
чужие рейсы возвращают 404, как несуществующие. Цены перевозчика, финансы и офисные поля в ответы
не попадают. Статусы меняются теми же правилами и сервисами, что в офисе (занятость техники,
официальный пробег по отчёту водителя), водителю доступны только три действия."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.audit.services import client_ip
from apps.core.handbooks.models import HandbookValue
from apps.drivers.models import Driver
from apps.forwarding.consignments.models import ConsignmentPoint
from apps.forwarding.models import Trip, TripConsignment
from apps.forwarding.trips.api import concurrency_guard
from apps.forwarding.trips.resources import effective_modules
from apps.forwarding.trips.serializers import TripStatusSerializer

ACTIVE_CODES = ("IN_PROGRESS", "UNLOADING")
FINISHED_CODES = ("COMPLETED", "CANCELLED")
# действие водителя -> (код нового статуса, из каких кодов доступно)
ACTIONS = {
    "start": ("IN_PROGRESS", ("PLANNED", "ASSIGNED")),
    "unloading": ("UNLOADING", ("IN_PROGRESS",)),
    "complete": ("COMPLETED", ("IN_PROGRESS", "UNLOADING")),
}
HISTORY_DAYS = 60
NOT_LINKED = "Ваш аккаунт не привязан к карточке водителя. Обратитесь в офис."


def driver_permissions():
    return [ModuleRequired("driver_app")(), permission_required("driver.use")()]


def current_driver(request) -> Driver:
    driver = Driver.objects.filter(user=request.user).exclude(status=Driver.INACTIVE).first()
    if driver is None:
        raise PermissionDenied(NOT_LINKED)
    return driver


def my_trips(driver: Driver):
    return Trip.objects.filter(driver=driver).select_related("status", "vehicle", "trailer")


def odometer_required(trip: Trip) -> bool:
    """Пробег машины обязателен при выезде и завершении, если у компании есть автопарк и на
    рейсе назначена техника (иначе записать показание некуда)."""
    return trip.vehicle_id is not None and "fleet" in effective_modules(trip.company_id)


def available_actions(trip: Trip) -> list[str]:
    code = trip.status.code
    return [name for name, (_, allowed) in ACTIONS.items() if code in allowed]


def _stops_of(trip: Trip) -> list[dict]:
    """Остановки рейса: точки участков (весь маршрут груза, если участок не задан), по времени."""
    seen: dict[int, dict] = {}
    for link in TripConsignment.objects.filter(trip=trip).select_related(
        "consignment", "from_stop", "to_stop"
    ):
        points = ConsignmentPoint.objects.filter(consignment=link.consignment)
        if link.from_stop_id and link.to_stop_id:
            points = points.filter(seq__gte=link.from_stop.seq, seq__lte=link.to_stop.seq)
        for p in points:
            seen.setdefault(
                p.pk,
                {
                    "id": p.pk,
                    "kind": p.kind,
                    "status": p.status,
                    "city": p.city,
                    "street": p.street,
                    "contact": p.contact,
                    "note": p.note,
                    "window_from": p.window_from,
                    "window_to": p.window_to,
                    "lat": p.lat,
                    "lng": p.lng,
                    "consignment": link.consignment.name,
                },
            )
    return sorted(seen.values(), key=lambda s: (s["window_from"], s["id"]))


class DriverMeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = [
            "id",
            "full_name",
            "phone",
            "license_number",
            "license_categories",
            "license_expires",
        ]


def trip_card(trip: Trip) -> dict:
    stops = _stops_of(trip)
    return {
        "id": trip.pk,
        "number": trip.number,
        "status": {"id": trip.status_id, "code": trip.status.code, "name": trip.status.name},
        "vehicle_plate": trip.vehicle.plate if trip.vehicle_id else trip.vehicle_plate,
        "trailer_plate": trip.trailer.plate if trip.trailer_id else "",
        "from_city": stops[0]["city"] if stops else "",
        "to_city": stops[-1]["city"] if stops else "",
        "starts_at": stops[0]["window_from"] if stops else None,
        "actions": available_actions(trip),
        "odometer_required": odometer_required(trip),
    }


class MeView(APIView):
    def get_permissions(self):
        return driver_permissions()

    def get(self, request):
        driver = current_driver(request)
        company = request.membership.company
        return Response(
            {
                "driver": DriverMeSerializer(driver).data,
                "company": {"id": company.pk, "name": company.name, "language": company.language},
            }
        )


class TripListView(APIView):
    """?scope=current (в пути), upcoming (ещё не выехал), history (завершённые за 60 дней)."""

    def get_permissions(self):
        return driver_permissions()

    def get(self, request):
        driver = current_driver(request)
        scope = request.query_params.get("scope", "current")
        if scope not in ("current", "upcoming", "history"):
            raise serializers.ValidationError({"scope": "Допустимо: current, upcoming, history"})
        qs = my_trips(driver)
        if scope == "current":
            qs = qs.filter(status__code__in=ACTIVE_CODES)
        elif scope == "upcoming":
            qs = qs.exclude(status__code__in=ACTIVE_CODES + FINISHED_CODES)
        else:
            since = timezone.now() - timedelta(days=HISTORY_DAYS)
            qs = qs.filter(status__code__in=FINISHED_CODES).filter(
                Q(completed_at__gte=since) | Q(completed_at__isnull=True, updated_at__gte=since)
            )
        trips = list(qs.order_by("-created_at")[:50])
        return Response({"results": [trip_card(t) for t in trips]})


def _own_trip(request, pk) -> Trip:
    trip = my_trips(current_driver(request)).filter(pk=pk).first()
    if trip is None:
        raise NotFound()
    return trip


class TripDetailView(APIView):
    def get_permissions(self):
        return driver_permissions()

    def get(self, request, pk):
        trip = _own_trip(request, pk)
        card = trip_card(trip)
        card["stops"] = _stops_of(trip)
        card["consignments"] = [
            {
                "name": link.consignment.name,
                "weight_kg": link.weight_kg or link.consignment.weight_kg,
            }
            for link in TripConsignment.objects.filter(trip=trip).select_related("consignment")
        ]
        return Response(card)


class ActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=list(ACTIONS))
    vehicle_km = serializers.IntegerField(required=False, min_value=1, max_value=10_000_000)
    trailer_km = serializers.IntegerField(required=False, min_value=0, max_value=10_000_000)


class TripActionView(APIView):
    """Выехал / разгрузка / завершил; пробег (необязательно) - при выезде и завершении."""

    def get_permissions(self):
        return driver_permissions()

    def post(self, request, pk):
        trip = _own_trip(request, pk)
        ser = ActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        code, allowed = ACTIONS[data["action"]]
        if trip.status.code not in allowed:
            raise serializers.ValidationError({"action": "Это действие сейчас недоступно"})
        if (
            data["action"] in ("start", "complete")
            and odometer_required(trip)
            and not data.get("vehicle_km")
        ):
            raise serializers.ValidationError({"vehicle_km": "Введите пробег машины"})
        if data["action"] == "unloading" and (data.get("vehicle_km") or data.get("trailer_km")):
            raise serializers.ValidationError(
                {"vehicle_km": "Пробег вносится при выезде и завершении"}
            )
        status = HandbookValue.objects.filter(
            handbook__code="trip_status", code=code, is_active=True
        ).first()
        if status is None:
            raise serializers.ValidationError({"action": "В компании нет нужного статуса рейса"})
        body = {"status": status.pk}
        for key in ("vehicle_km", "trailer_km"):
            if key in data:
                body[key] = data[key]
        inner = TripStatusSerializer(data=body)
        inner.is_valid(raise_exception=True)
        with concurrency_guard():
            inner.save(trip, request.user, ip=client_ip(request))
        trip = my_trips(trip.driver).get(pk=trip.pk)
        card = trip_card(trip)
        card["stops"] = _stops_of(trip)
        return Response(card)
