"""Синхронизация с Wialon: юниты, привязка к технике, геозоны, события."""

import hmac
import ipaddress
import logging
import re
import socket
from datetime import UTC, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.fleet.models import Vehicle

from . import crypto, geometry
from .models import Geofence, GeofenceEvent, GpsUnit, VehicleGeofenceState, WialonAccount
from .wialon import WialonAPIError, WialonClient

logger = logging.getLogger(__name__)

ENTER_WORDS = {"enter", "in", "entered", "arrive", "arrival", "въезд", "вход"}
EXIT_WORDS = {"exit", "out", "left", "leave", "departure", "выезд", "выход"}
MIN_PLATE_LEN = 4
ADDRESS_LOOKUPS_MAX = 40  # адреса через отчёт Wialon: по одному запросу на юнит, с потолком


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]", "", (text or "").lower())


def ensure_public_base_url(url: str) -> None:
    """Сервер Wialon: только https и публичный адрес (защита от SSRF)."""
    from urllib.parse import urlparse

    from django.conf import settings
    from rest_framework.exceptions import ValidationError

    if getattr(settings, "GPS_ALLOW_PRIVATE_HOSTS", False):
        return
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValidationError({"base_url": "Адрес сервера Wialon должен начинаться с https://"})
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError:
        raise ValidationError(
            {"base_url": "Не удалось найти сервер Wialon по этому адресу"}
        ) from None
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValidationError(
                {"base_url": "Адрес сервера ведёт во внутреннюю сеть: он не разрешён"}
            )


def client_for(account: WialonAccount) -> WialonClient:
    return WialonClient(token=crypto.decrypt(account.token_enc), base_url=account.base_url)


def match_vehicle(unit_name: str, vehicles) -> Vehicle | None:
    """Техника, чей госномер содержится в названии юнита («886AIA14», «Volvo 886 AIA 14»):
    пробелы и регистр не важны, при нескольких совпадениях побеждает более длинный номер."""
    wanted = normalize(unit_name)
    if not wanted:
        return None
    hits = [
        v for v in vehicles
        if len(normalize(v.plate)) >= MIN_PLATE_LEN and normalize(v.plate) in wanted
    ]  # fmt: skip
    return max(hits, key=lambda v: len(normalize(v.plate))) if hits else None


def _dt(unix) -> datetime | None:
    return datetime.fromtimestamp(unix, tz=UTC) if unix else None


def _dec(value, places) -> Decimal | None:
    return None if value is None else Decimal(str(round(float(value), places)))


def sync_units(account: WialonAccount, client: WialonClient | None = None) -> dict:
    """Загружает юниты Wialon, обновляет снимок и автоматически привязывает новые юниты к технике
    по госномеру в названии (ручные привязки не трогаются)."""
    client = client or client_for(account)
    units = client.list_units()
    now = timezone.now()
    vehicles = list(Vehicle.objects.all())
    linked_ids = set(
        GpsUnit.objects.filter(vehicle__isnull=False).values_list("vehicle_id", flat=True)
    )
    existing = {u.unit_id: u for u in GpsUnit.objects.all()}
    template = None
    try:
        template = client.find_report_template()
    except WialonAPIError as exc:
        logger.warning("Wialon: шаблон отчёта не найден: %s", exc)
    result = {
        "units_seen": len(units),
        "created": 0,
        "updated": 0,
        "auto_linked": 0,
        "no_sensor": [],
    }
    addresses = 0
    for item in units:
        unit_id = str(item.get("id"))
        unit = existing.get(unit_id)
        created = unit is None
        if created:
            unit = GpsUnit(unit_id=unit_id)
        unit.name = (item.get("nm") or unit_id)[:255]
        unit.seen_at = now
        pos = client.extract_position(item)
        if pos:
            unit.lat, unit.lon = _dec(pos["lat"], 6), _dec(pos["lon"], 6)
            unit.speed_kmh = int(pos["speed"]) if pos.get("speed") is not None else None
            unit.position_at = _dt(pos.get("timestamp")) or now
        mileage = client.extract_mileage_km(item)
        if mileage is not None:
            unit.odometer_km, unit.odometer_at = _dec(mileage, 1), now
        fuel = client.extract_fuel_level_l(item)
        if fuel is not None:
            unit.fuel_level_l, unit.fuel_level_at = _dec(fuel, 1), now
        else:
            result["no_sensor"].append({"unit_id": unit_id, "name": unit.name})
        if unit.vehicle_id is None:
            free = [v for v in vehicles if v.pk not in linked_ids]
            match = match_vehicle(unit.name, free)
            if match is not None:
                unit.vehicle = match
                linked_ids.add(match.pk)
                result["auto_linked"] += 1
        if template and unit.vehicle_id and addresses < ADDRESS_LOOKUPS_MAX:
            addresses += 1
            try:
                loc = client.get_last_location(*template, unit_id=int(unit_id))
            except (WialonAPIError, ValueError) as exc:
                logger.warning("Wialon: адрес юнита %s: %s", unit_id, exc)
                loc = None
            if loc:
                unit.location_text = loc["text"][:500]
        unit.save()
        result["created" if created else "updated"] += 1
        if unit.vehicle_id and pos:
            check_geofences(unit.vehicle, pos["lat"], pos["lon"], unit.position_at or now)
    return result


def sync_geofences(account: WialonAccount, client: WialonClient | None = None) -> dict:
    """Зеркалит геозоны Wialon (геометрия и название - из Wialon, тип и «активна» - за офисом).
    Удалённая в Wialon зона выключается, а не удаляется: история событий сохраняется."""
    client = client or client_for(account)
    zones = client.list_zones()
    created = updated = skipped = 0
    seen: list[int] = []
    for item in zones:
        geo = geometry.parse_wialon_zone(item["raw"])
        if geo is None:
            skipped += 1
            continue
        name = (item["raw"].get("n") or "Геозона Wialon")[:255]
        fields = {
            "name": name, "shape": geo["shape"],
            "lat": _dec(geo["lat"], 6), "lon": _dec(geo["lon"], 6),
            "radius_m": geo["radius_m"], "polygon": geo["polygon"],
            "is_approximate": geo["approximate"], "source": Geofence.WIALON,
        }  # fmt: skip
        gf = Geofence.objects.filter(
            wialon_resource_id=item["resource_id"], wialon_zone_id=item["zone_id"]
        ).first()
        if gf is None:
            gf = Geofence(
                wialon_resource_id=item["resource_id"], wialon_zone_id=item["zone_id"],
                kind=guess_kind(name), **fields,
            )  # fmt: skip
            gf.save()
            created += 1
        else:
            for attr, value in fields.items():
                setattr(gf, attr, value)
            gf.save()
            updated += 1
        seen.append(gf.pk)
    deactivated = 0
    if seen:  # пустой ответ скорее «зоны не прочитаны», чем «все удалены»
        deactivated = (
            Geofence.objects.filter(source=Geofence.WIALON, is_active=True)
            .exclude(pk__in=seen)
            .update(is_active=False)
        )
    return {"zones_seen": len(zones), "created": created, "updated": updated,
            "skipped": skipped, "deactivated": deactivated}  # fmt: skip


_KIND_WORDS = (
    (Geofence.BORDER, ("погран", "граница", "таможн", "кпп", "border", "customs")),
    (Geofence.WAREHOUSE, ("склад", "база", "терминал", "депо", "warehouse", "depot", "base")),
    (Geofence.CITY, ("город", "г.", "city")),
)


def guess_kind(name: str) -> str:
    lowered = name.lower()
    for kind, words in _KIND_WORDS:
        if any(w in lowered for w in words):
            return kind
    return Geofence.OTHER


def is_inside(geofence: Geofence, lat, lon) -> bool:
    if geofence.shape == Geofence.POLYGON and geofence.polygon:
        return geometry.point_in_polygon(lat, lon, geofence.polygon)
    return geometry.distance_m(lat, lon, geofence.lat, geofence.lon) <= geofence.radius_m


def record_event(vehicle: Vehicle, geofence: Geofence, event_type: str, at) -> bool:
    """Пишет въезд/выезд, если он меняет известное состояние (Wialon может прислать повторно).
    True - записано новое событие."""
    inside = event_type == GeofenceEvent.ENTER
    state = VehicleGeofenceState.objects.filter(vehicle=vehicle, geofence=geofence).first()
    if state is not None and state.is_inside == inside:
        return False
    with transaction.atomic():
        GeofenceEvent.objects.create(
            geofence=geofence, vehicle=vehicle, event_type=event_type, occurred_at=at
        )
        if state is None:
            VehicleGeofenceState.objects.create(
                vehicle=vehicle, geofence=geofence, is_inside=inside
            )
        else:
            state.is_inside = inside
            state.save(update_fields=["is_inside", "updated_at"])
    return True


def check_geofences(vehicle: Vehicle, lat, lon, at) -> int:
    """Сравнивает позицию с активными зонами, пишет событие на каждый переход (их число)."""
    recorded = 0
    for geofence in Geofence.objects.filter(is_active=True):
        now_inside = is_inside(geofence, lat, lon)
        known = VehicleGeofenceState.objects.filter(vehicle=vehicle, geofence=geofence).first()
        if known is None and not now_inside:
            continue  # техника никогда не была в зоне и не в ней: события нет
        kind = GeofenceEvent.ENTER if now_inside else GeofenceEvent.EXIT
        if record_event(vehicle, geofence, kind, at):
            recorded += 1
    return recorded


def sync_account(account: WialonAccount) -> dict:
    """Полная синхронизация: сначала геозоны (позиции проверяются по свежим зонам), затем юниты."""
    client = client_for(account)
    result = {}
    try:
        try:
            result["geofences"] = sync_geofences(account, client)
        except Exception as exc:  # noqa: BLE001 - зоны не должны ломать синхронизацию юнитов
            logger.warning("Wialon: геозоны: %s", type(exc).__name__)
            result["geofences_error"] = type(exc).__name__
        result["units"] = sync_units(account, client)
    except WialonAPIError as exc:
        account.last_sync_error = str(exc)[:500]
        account.save(update_fields=["last_sync_error"])
        raise
    account.last_synced_at = timezone.now()
    account.last_sync_error = ""
    account.save(update_fields=["last_synced_at", "last_sync_error"])
    return result


def webhook_event_type(word: str) -> str | None:
    word = (word or "").strip().lower()
    if word in ENTER_WORDS:
        return GeofenceEvent.ENTER
    if word in EXIT_WORDS:
        return GeofenceEvent.EXIT
    return None


def secret_matches(account: WialonAccount, secret: str) -> bool:
    return bool(account.webhook_secret) and hmac.compare_digest(
        account.webhook_secret, secret or ""
    )


def find_geofences_by_name(zone_field: str) -> list[Geofence]:
    """%ZONE% Wialon: одно имя или несколько через запятую (пересекающиеся зоны)."""
    active = list(Geofence.objects.filter(is_active=True))
    found: list[Geofence] = []
    for name in [n.strip() for n in (zone_field or "").split(",") if n.strip()]:
        candidates = [g for g in active if g.name.strip().casefold() == name.casefold()]
        candidates.sort(key=lambda g: g.source != Geofence.WIALON)  # зона Wialon главнее ручной
        if candidates and candidates[0] not in found:
            found.append(candidates[0])
    return found


# --- источник GPS-пробега для fleet.services.mileage_check ---------------------------------------


def gps_mileage_source(vehicle, now):
    """(км, время получения) по привязанному юниту или None, если данных нет."""
    unit = (
        GpsUnit.objects.filter(
            vehicle=vehicle, odometer_km__isnull=False, odometer_at__isnull=False
        )
        .order_by("-odometer_at")
        .first()
    )
    if unit is None:
        return None
    return int(unit.odometer_km), unit.odometer_at


# --- сверка заправок отчёта с датчиком топлива ----------------------------------------------------

FUEL_TOLERANCE_PCT = 5  # допустимое расхождение, % от литров по GPS
FUEL_TOLERANCE_L = 20  # и не меньше этого числа литров (датчик неточен на малых объёмах)


def fuel_fillings(vehicle: Vehicle, dt_from: datetime, dt_to: datetime, client=None) -> dict:
    """Заправки техники за период по датчику Wialon. Чтение: ничего не сохраняется.

    available=False с причиной: нет аккаунта, нет привязанного юнита, нет шаблона отчёта в Wialon
    или Wialon недоступен. Причина не ошибка: сверка просто показывает «данные недоступны»."""
    result = {"available": False, "reason": "", "fillings": [], "total_l": None}
    account = WialonAccount.objects.filter(is_active=True).first()
    if account is None or not account.token_enc:
        result["reason"] = "no_account"
        return result
    unit = GpsUnit.objects.filter(vehicle=vehicle).first()
    if unit is None:
        result["reason"] = "no_unit"
        return result
    try:
        client = client or client_for(account)
        template = client.find_report_template()
        if template is None:
            result["reason"] = "no_report_template"
            return result
        rows = client.get_fuel_fillings(
            *template, int(unit.unit_id), int(dt_from.timestamp()), int(dt_to.timestamp())
        )
    except (WialonAPIError, ValueError) as exc:
        logger.warning("Wialon: заправки юнита %s: %s", unit.unit_id, exc)
        result["reason"] = "wialon_error"
        return result
    result["fillings"] = [
        {"at": _dt(r["timestamp"]), "liters": round(float(r["filled_l"]), 1)} for r in rows
    ]
    result["total_l"] = round(sum(r["liters"] for r in result["fillings"]), 1)
    result["available"] = True
    return result


def compare_fuel(reported_l, gps_l) -> dict:
    """Сравнение литров по отчёту с заправками по датчику.

    Расхождение подсвечивается, если оно больше допуска: максимум из FUEL_TOLERANCE_L литров и
    FUEL_TOLERANCE_PCT % от литров по GPS. Нет данных GPS - сравнения нет (warning=False)."""
    reported = None if reported_l in (None, "") else round(float(reported_l), 1)
    gps = None if gps_l is None else round(float(gps_l), 1)
    out = {"reported_l": reported, "gps_l": gps, "difference_l": None, "warning": False}
    if reported is None or gps is None:
        return out
    diff = round(reported - gps, 1)
    out["difference_l"] = diff
    out["warning"] = abs(diff) > max(FUEL_TOLERANCE_L, gps * FUEL_TOLERANCE_PCT / 100)
    return out


# --- трек ---------------------------------------------------------------------------------------

TRACK_MAX_POINTS = 800  # точек на карте не больше: длинные треки прореживаются равномерно


def downsample(points: list[dict], limit: int = TRACK_MAX_POINTS) -> list[dict]:
    """Равномерно оставляет не больше limit точек; первая и последняя сохраняются."""
    if len(points) <= limit or limit < 2:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


def track_length_km(points: list[dict]) -> float:
    return round(
        sum(
            geometry.distance_m(a["lat"], a["lon"], b["lat"], b["lon"])
            for a, b in zip(points, points[1:], strict=False)
        )
        / 1000,
        1,
    )


def unit_track(unit: GpsUnit, dt_from: datetime, dt_to: datetime, client=None) -> dict:
    """Трек привязанного или любого юнита за период. Чтение: ничего не сохраняется.
    available=False с причиной: нет аккаунта или Wialon недоступен."""
    result = {"available": False, "reason": "", "points": [], "total_points": 0, "length_km": None}
    account = WialonAccount.objects.filter(is_active=True).first()
    if account is None or not account.token_enc:
        result["reason"] = "no_account"
        return result
    try:
        client = client or client_for(account)
        raw = client.get_track(int(unit.unit_id), int(dt_from.timestamp()), int(dt_to.timestamp()))
    except (WialonAPIError, ValueError) as exc:
        logger.warning("Wialon: трек юнита %s: %s", unit.unit_id, exc)
        result["reason"] = "wialon_error"
        return result
    result.update(
        available=True,
        total_points=len(raw),
        length_km=track_length_km(raw),
        points=[
            {"t": _dt(p["t"]), "lat": round(float(p["lat"]), 6), "lon": round(float(p["lon"]), 6),
             "speed": p.get("speed")}
            for p in downsample(raw)
        ],
    )  # fmt: skip
    return result
