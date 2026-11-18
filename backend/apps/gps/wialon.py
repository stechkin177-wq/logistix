"""Клиент Wialon Remote API (hst-api.wialon.com или свой сервер). Перенесён из truck365:
таймауты, единое сообщение об ошибке без токена, разбор зон с контурами.

Справка: https://sdk.wialon.com/wiki/en/sidebar/remoteapi/apiref/apiref
"""

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

# core/search_items "flags": 1 базовые данные, 1024 последнее сообщение (позиция), 4096 датчики,
# 8192 счётчики (пробег cnm)
FLAGS_BASE = 1
FLAGS_LAST_MESSAGE = 1024
FLAGS_SENSORS = 4096
FLAGS_COUNTERS = 8192
DEFAULT_BASE_URL = "https://hst-api.wialon.com"
TIMEOUT = 20


class WialonAPIError(Exception):
    """Ошибка Wialon или сети. Текст безопасен для показа (без токена)."""


class WialonClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL):
        self.token = token
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.sid = None

    def _request(self, svc: str, params: dict) -> dict:
        url = f"{self.base_url}/wialon/ajax.html"
        payload = {"svc": svc, "params": json.dumps(params)}
        if self.sid:
            payload["sid"] = self.sid
        body = urllib.parse.urlencode(payload).encode()
        request = urllib.request.Request(url, data=body, method="POST")  # noqa: S310 - https, адрес проверен
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WialonAPIError(f"Wialon недоступен: {type(exc).__name__}") from None
        except ValueError:
            raise WialonAPIError("Wialon вернул не JSON") from None
        if isinstance(data, dict) and data.get("error"):
            raise WialonAPIError(f"Wialon: ошибка {data['error']} в {svc}")
        return data

    def login(self) -> dict:
        data = self._request("token/login", {"token": self.token})
        self.sid = data.get("eid")
        if not self.sid:
            raise WialonAPIError("Wialon не вернул сессию")
        return data

    def ensure_session(self):
        if not self.sid:
            self.login()

    def list_units(self) -> list[dict]:
        """Юниты: id, название, последняя позиция, датчики и счётчики."""
        self.ensure_session()
        data = self._request(
            "core/search_items",
            {
                "spec": {
                    "itemsType": "avl_unit", "propName": "sys_name",
                    "propValueMask": "*", "sortType": "sys_name",
                },
                "force": 1,
                "flags": FLAGS_BASE | FLAGS_LAST_MESSAGE | FLAGS_SENSORS | FLAGS_COUNTERS,
                "from": 0,
                "to": 0,
            },
        )  # fmt: skip
        return data.get("items", [])

    @staticmethod
    def extract_mileage_km(unit_item: dict) -> float | None:
        """Счётчик пробега, настроенный в аккаунте (cnm, км). None - у юнита счётчика нет."""
        cnm = unit_item.get("cnm")
        if cnm is None:
            return None
        return round(float(cnm), 1)

    @staticmethod
    def _calibrated_sensor_value(sensor: dict, raw_params: dict) -> float | None:
        """Значение аналогового датчика по таблице тарировки (кусочно-линейной)."""
        param_key = sensor.get("p")
        table = sensor.get("tbl") or []
        if not param_key or not table or param_key not in raw_params:
            return None
        raw = raw_params[param_key]
        segment = table[0]
        for seg in table:
            if seg["x"] <= raw:
                segment = seg
            else:
                break
        return segment["a"] * raw + segment["b"]

    @staticmethod
    def _find_fuel_sensor(sensors: dict) -> dict | None:
        """Датчик топлива: «fuel level», иначе формула-сумма баков «[Бак 1]+[Бак 2]»."""
        for sensor in sensors.values():
            if sensor.get("t") == "fuel level":
                return sensor
        for sensor in sensors.values():
            if re.search(r"\[[^\]]+\]", sensor.get("p") or ""):
                return sensor
        return None

    @classmethod
    def extract_fuel_level_l(cls, unit_item: dict) -> float | None:
        """Суммарный уровень топлива, л (по тарировке баков). None - датчика или тарировки нет."""
        sensors = unit_item.get("sens") or {}
        raw_params = ((unit_item.get("lmsg") or {}).get("p")) or {}
        fuel_sensor = cls._find_fuel_sensor(sensors)
        if not fuel_sensor:
            return None
        tank_names = re.findall(r"\[([^\]]+)\]", fuel_sensor.get("p") or "")
        if not tank_names:
            value = cls._calibrated_sensor_value(fuel_sensor, raw_params)
            return round(value, 1) if value is not None else None
        by_name = {s.get("n"): s for s in sensors.values()}
        total, found = 0.0, False
        for name in tank_names:
            tank = by_name.get(name)
            if not tank:
                continue
            value = cls._calibrated_sensor_value(tank, raw_params)
            if value is not None:
                total += value
                found = True
        return round(total, 1) if found else None

    @staticmethod
    def extract_position(unit_item: dict) -> dict | None:
        pos = unit_item.get("pos")
        if not pos or pos.get("y") is None or pos.get("x") is None:
            return None
        return {"lat": pos["y"], "lon": pos["x"], "speed": pos.get("s"), "timestamp": pos.get("t")}

    def find_report_template(self) -> tuple[int, int] | None:
        """Пара (ресурс, шаблон) для report/exec_report: первый ресурс с шаблоном отчёта.
        Шаблоны диспетчеры строят в веб-интерфейсе Wialon. None - шаблонов нет (адреса и заправки
        по датчику недоступны)."""
        self.ensure_session()
        data = self._request(
            "core/search_items",
            {
                "spec": {
                    "itemsType": "avl_resource", "propName": "sys_name",
                    "propValueMask": "*", "sortType": "sys_name",
                },
                "force": 1,
                "flags": 1 | 8192,
                "from": 0,
                "to": 0,
            },
        )  # fmt: skip
        for resource in data.get("items", []):
            templates = resource.get("rep") or {}
            if templates:
                return resource["id"], next(iter(templates.values()))["id"]
        return None

    def list_zones(self) -> list[dict]:
        """Геозоны всех ресурсов токена: {resource_id, zone_id, raw}. raw: n имя, t тип (1 линия,
        2 полигон, 3 круг), b рамка, p точки [{x lon, y lat, r}]."""
        self.ensure_session()
        data = self._request(
            "core/search_items",
            {
                "spec": {
                    "itemsType": "avl_resource", "propName": "sys_name",
                    "propValueMask": "*", "sortType": "sys_name",
                },
                "force": 1,
                "flags": 1 | 0x400 | 0x800 | 0x1000 | 0x2000 | 0x4000,
                "from": 0,
                "to": 0,
            },
        )  # fmt: skip
        zones = []
        for resource in data.get("items", []):
            for zone_key, zone in (resource.get("zl") or {}).items():
                if isinstance(zone, dict):
                    zones.append(
                        {
                            "resource_id": str(resource.get("id")),
                            "zone_id": str(zone.get("id", zone_key)),
                            "raw": zone,
                        }
                    )
        return zones

    def _exec_report(self, resource_id, template_id, unit_id, dt_from, dt_to) -> list[dict]:
        self.ensure_session()
        result = self._request(
            "report/exec_report",
            {
                "reportResourceId": resource_id, "reportTemplateId": template_id,
                "reportObjectId": unit_id, "reportObjectSecId": 0,
                "interval": {"from": dt_from, "to": dt_to, "flags": 0},
            },
        )  # fmt: skip
        return (result.get("reportResult") or {}).get("tables") or []

    def _table_rows(self, tables, name, first=0, last=None) -> list[dict]:
        idx = next((i for i, t in enumerate(tables) if t.get("name") == name), None)
        if idx is None or not tables[idx].get("rows"):
            return []
        n = tables[idx]["rows"]
        rows = self._request(
            "report/get_result_rows",
            {"tableIndex": idx, "indexFrom": n - 1 if last == "tail" else first, "indexTo": n},
        )
        return rows or []

    def get_fuel_fillings(self, resource_id, template_id, unit_id, dt_from, dt_to) -> list[dict]:
        """Заправки юнита за период (unix) из таблицы unit_fillings: [{timestamp, filled_l}].
        Пустой список - заправок нет (нормально, не ошибка)."""
        tables = self._exec_report(resource_id, template_id, unit_id, dt_from, dt_to)
        try:
            rows = self._table_rows(tables, "unit_fillings")
        finally:
            self._request("report/cleanup_result", {})
        fillings = []
        for row in rows:
            cols = row.get("c") or []  # [#, время, место, было, залито, стало]
            if len(cols) < 5:
                continue
            time_col = cols[1]
            timestamp = time_col.get("v") if isinstance(time_col, dict) else row.get("t2")
            match = re.match(r"([\d.]+)", str(cols[4]).strip())
            if match:
                fillings.append({"timestamp": timestamp, "filled_l": float(match.group(1))})
        return fillings

    def get_last_location(self, resource_id, template_id, unit_id, lookback_days=3) -> dict | None:
        """Адрес текстом по последней стоянке или рейсу из отчёта (общий способ без геокодера)."""
        dt_to = int(time.time())
        tables = self._exec_report(
            resource_id, template_id, unit_id, dt_to - lookback_days * 86400, dt_to
        )
        candidates = []
        try:
            for name in ("unit_stays", "unit_trips"):
                rows = self._table_rows(tables, name, last="tail")
                row = rows[0] if rows else None
                cols = (row or {}).get("c") or []
                if len(cols) > 4:
                    end_time, pos = cols[2], cols[4]
                    ts = end_time.get("v") if isinstance(end_time, dict) else (row or {}).get("t2")
                    text = pos.get("t") if isinstance(pos, dict) else None
                    if text:
                        candidates.append((ts or 0, text))
        finally:
            self._request("report/cleanup_result", {})
        if not candidates:
            return None
        ts, text = max(candidates, key=lambda c: c[0])
        return {"text": text, "timestamp": ts}
