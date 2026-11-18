"""Геометрия геозон: расстояние, точка в круге и в контуре, разбор зон Wialon."""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000
MIN_ZONE_RADIUS_M = 30
MAX_POLYGON_POINTS = 500


def distance_m(lat1, lon1, lat2, lon2) -> float:
    """Расстояние по дуге большого круга (формула гаверсинусов), метры."""
    lat1, lon1, lat2, lon2 = map(radians, (float(lat1), float(lon1), float(lat2), float(lon2)))
    d_lat, d_lon = lat2 - lat1, lon2 - lon1
    a = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def point_in_polygon(lat, lon, polygon) -> bool:
    """Точка внутри контура (метод луча). polygon - список пар [lat, lon]; контур замыкается сам."""
    x, y = float(lon), float(lat)
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = float(polygon[i][0]), float(polygon[i][1])
        yj, xj = float(polygon[j][0]), float(polygon[j][1])
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def enclosing_circle(polygon) -> tuple[float, float, int]:
    """Круг вокруг контура (центр - середина рамки): (lat, lon, радиус м). Для показа на карте."""
    lats = [float(p[0]) for p in polygon]
    lons = [float(p[1]) for p in polygon]
    lat, lon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    radius = max(distance_m(lat, lon, p[0], p[1]) for p in polygon)
    return lat, lon, max(int(round(radius)), MIN_ZONE_RADIUS_M)


def simplify(polygon, limit=MAX_POLYGON_POINTS):
    """Прореживает слишком длинный контур, сохраняя форму (равномерно по точкам)."""
    if len(polygon) <= limit:
        return polygon
    step = len(polygon) / limit
    return [polygon[int(i * step)] for i in range(limit)]


def parse_wialon_zone(zone: dict):
    """Зона Wialon как dict с геометрией или None, если геометрии нет.

    t: 1 линия, 2 полигон, 3 круг. Круг передаётся точно, полигон хранится контуром (проверка
    «внутри» точная), линия - как узкая область вокруг центра (приближённо)."""
    points = [
        p for p in (zone.get("p") or [])
        if isinstance(p, dict) and p.get("x") is not None and p.get("y") is not None
    ]  # fmt: skip
    box = zone.get("b") or {}
    if zone.get("t") == 3 and points:
        first = points[0]
        radius = first.get("r") or zone.get("w") or 0
        return {
            "shape": "circle", "lat": float(first["y"]), "lon": float(first["x"]),
            "radius_m": max(int(round(float(radius))), MIN_ZONE_RADIUS_M),
            "polygon": None, "approximate": False,
        }  # fmt: skip
    if zone.get("t") == 2 and len(points) >= 3:
        polygon = simplify([[float(p["y"]), float(p["x"])] for p in points])
        lat, lon, radius = enclosing_circle(polygon)
        return {
            "shape": "polygon", "lat": lat, "lon": lon, "radius_m": radius,
            "polygon": polygon, "approximate": False,
        }  # fmt: skip
    if box.get("cen_x") is not None and box.get("cen_y") is not None:
        lon, lat = float(box["cen_x"]), float(box["cen_y"])
    elif points:
        lon = sum(float(p["x"]) for p in points) / len(points)
        lat = sum(float(p["y"]) for p in points) / len(points)
    else:
        return None
    if points:
        radius = max(distance_m(lat, lon, p["y"], p["x"]) for p in points)
    elif box.get("min_x") is not None and box.get("max_y") is not None:
        radius = distance_m(lat, lon, box["max_y"], box["max_x"])
    else:
        radius = MIN_ZONE_RADIUS_M
    return {
        "shape": "circle", "lat": lat, "lon": lon,
        "radius_m": max(int(round(radius)), MIN_ZONE_RADIUS_M),
        "polygon": None, "approximate": True,
    }  # fmt: skip
