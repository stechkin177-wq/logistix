"""Мобильная версия водителя (модуль driver_app): «я», мои рейсы, карточка рейса, действия.

Изоляция: водитель видит ТОЛЬКО рейсы, где Trip.driver - его карточка (Driver.user = он сам);
чужие рейсы возвращают 404, как несуществующие. Цены перевозчика, финансы и офисные поля в ответы
не попадают. Статусы меняются теми же правилами и сервисами, что в офисе (занятость техники,
официальный пробег по отчёту водителя), водителю доступны только три действия."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.audit.services import client_ip
from apps.core.handbooks.models import HandbookValue
from apps.drivers.models import Driver
from apps.fleet import services as fleet_services
from apps.forwarding.consignments.models import ConsignmentPoint
from apps.forwarding.models import Trip, TripConsignment
from apps.forwarding.trips.api import concurrency_guard
from apps.forwarding.trips.resources import effective_modules
from apps.forwarding.trips.serializers import TripStatusSerializer
from apps.ocr import services as ocr_services
from apps.ocr import storage as ocr_storage
from apps.ocr.api import DocumentSerializer, UploadThrottle
from apps.ocr.models import ScannedDocument

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


def _fleet_on(trip: Trip) -> bool:
    return "fleet" in effective_modules(trip.company_id)


def odometer_required(trip: Trip) -> bool:
    """Пробег машины обязателен при ЗАВЕРШЕНИИ рейса, если есть автопарк и назначена техника
    (иначе записать показание некуда). При выезде водитель пробег не вводит: берётся последнее
    официальное показание машины (пробег завершения прошлого рейса)."""
    return trip.vehicle_id is not None and _fleet_on(trip)


def refrigerated_units(trip: Trip) -> list:
    """Техника рейса с холодильной установкой (прицеп-рефрижератор или рефрижераторный грузовик)."""
    if not _fleet_on(trip):
        return []
    return [u for u in (trip.trailer, trip.vehicle) if u is not None and u.has_refrigerator]


def engine_hours_required(trip: Trip) -> bool:
    return bool(refrigerated_units(trip))


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


def _current_hours(trip: Trip):
    units = refrigerated_units(trip)
    return fleet_services.latest_engine_hours(units[0].pk) if units else None


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
        "current_odometer_km": (
            fleet_services.latest_odometer(trip.vehicle_id)
            if trip.vehicle_id and _fleet_on(trip)
            else None
        ),
        "engine_hours_required": engine_hours_required(trip),
        "current_engine_hours": _current_hours(trip),
        "reefer_plate": (refrigerated_units(trip)[0].plate if refrigerated_units(trip) else ""),
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
    engine_hours = serializers.DecimalField(
        required=False, max_digits=9, decimal_places=1, min_value=0
    )


class TripActionView(APIView):
    """Выехал / разгрузка / завершил; пробег (необязательно) - при выезде и завершении."""

    def get_permissions(self):
        return driver_permissions()

    def post(self, request, pk):
        trip = _own_trip(request, pk)
        ser = ActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        action = data["action"]
        code, allowed = ACTIONS[action]
        if trip.status.code not in allowed:
            raise serializers.ValidationError({"action": "Это действие сейчас недоступно"})
        if action == "unloading" and ("vehicle_km" in data or "engine_hours" in data):
            raise serializers.ValidationError(
                {"vehicle_km": "Пробег вносится при завершении, моточасы - при выезде и завершении"}
            )
        if action == "complete":
            if odometer_required(trip) and not data.get("vehicle_km"):
                raise serializers.ValidationError({"vehicle_km": "Введите пробег машины"})
            if engine_hours_required(trip) and data.get("engine_hours") is None:
                raise serializers.ValidationError({"engine_hours": "Введите моточасы установки"})
        status = HandbookValue.objects.filter(
            handbook__code="trip_status", code=code, is_active=True
        ).first()
        if status is None:
            raise serializers.ValidationError({"action": "В компании нет нужного статуса рейса"})
        km = data.get("vehicle_km")
        if action == "start" and km is None and trip.vehicle_id and _fleet_on(trip):
            # выезд: пробег выезда = последнее показание машины (завершение прошлого рейса)
            km = fleet_services.latest_odometer(trip.vehicle_id)
        body = {"status": status.pk}
        if km is not None and trip.vehicle_id:
            body["vehicle_km"] = km
        inner = TripStatusSerializer(data=body)
        inner.is_valid(raise_exception=True)
        phase = "start" if action == "start" else "end"
        with concurrency_guard(), transaction.atomic():
            inner.save(trip, request.user, ip=client_ip(request))
            if action in ("start", "complete"):
                for unit in refrigerated_units(trip):
                    hours = data.get("engine_hours")
                    if hours is None and action == "start":
                        hours = fleet_services.latest_engine_hours(unit.pk)
                    if hours is not None:
                        fleet_services.record_trip_engine_hours(trip, unit, hours, phase)
        trip = my_trips(trip.driver).get(pk=trip.pk)
        card = trip_card(trip)
        card["stops"] = _stops_of(trip)
        return Response(card)


# --- отчёты водителя: фото листа, чеков и документов (модуль ocr) ---

REPORT_TYPES = ("report_sheet", "fuel_receipt", "waybill", "cmr", "other")


def report_permissions():
    return [*driver_permissions(), ModuleRequired("ocr")()]


class ReportListView(APIView):
    """GET - свои отправленные документы (?trip=); POST multipart - отправить фото (file,
    doc_type, trip): распознаётся сразу, сомнительные значения подсвечиваются, офис видит
    документ в «Распознавании» с рейсом и водителем."""

    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        return report_permissions()

    def get_throttles(self):
        return [UploadThrottle()] if self.request.method == "POST" else []

    def get(self, request):
        driver = current_driver(request)
        qs = ScannedDocument.objects.filter(driver=driver).select_related("trip", "driver")
        if trip := request.query_params.get("trip"):
            qs = qs.filter(trip_id=trip) if trip.isdigit() else qs.none()
        return Response({"results": DocumentSerializer(qs[:50], many=True).data})

    def post(self, request):
        driver = current_driver(request)
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Выберите файл"})
        if upload.size > ocr_services.MAX_BYTES:
            raise serializers.ValidationError({"file": "Файл больше 4 МБ: сожмите фото"})
        data = upload.read()
        content_type = ocr_services.sniff(data)
        if content_type is None:
            raise serializers.ValidationError({"file": "Нужна картинка JPEG или PNG"})
        doc_type = request.data.get("doc_type") or "other"
        if doc_type not in REPORT_TYPES:
            raise serializers.ValidationError({"doc_type": "Недопустимый тип документа"})
        trip = None
        if request.data.get("trip"):
            trip = (
                my_trips(driver).filter(pk=str(request.data["trip"])).first()
                if str(request.data["trip"]).isdigit()
                else None
            )
            if trip is None:
                raise serializers.ValidationError({"trip": "Это не ваш рейс"})
        doc = ocr_services.scan(
            data, content_type, upload.name or "", doc_type, request.user,
            driver=driver, trip=trip, source=ScannedDocument.DRIVER_APP,
        )  # fmt: skip
        doc = ScannedDocument.objects.select_related("trip", "driver").get(pk=doc.pk)
        return Response(DocumentSerializer(doc).data, status=201)


class ReportDetailView(APIView):
    """DELETE - убрать свой документ (переснять), пока офис его не проверил."""

    def get_permissions(self):
        return report_permissions()

    def delete(self, request, pk):
        driver = current_driver(request)
        doc = ScannedDocument.objects.filter(pk=pk, driver=driver).first()
        if doc is None:
            raise NotFound()
        if doc.reviewed_at is not None:
            raise serializers.ValidationError({"detail": "Документ уже проверен офисом"})
        key = doc.file_key
        doc.delete()
        if key and ocr_storage.configured():
            ocr_storage.delete(key)
        return Response(status=204)
