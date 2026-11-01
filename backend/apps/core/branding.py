"""Оформление компании (брендинг): значения по умолчанию, проверки и публичный поиск.

CompanyBranding - ОБЫЧНАЯ модель (не TenantModel, без RLS): публичный эндпоинт экрана входа
обязан читать её до появления контекста компании. Это принятый пробел вместе с Company,
Subscription и Plan; изоляция обеспечивается кодом (компания берётся из членства запроса).
"""

import re
import uuid
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError

PLATFORM_APP_NAME = "Logistix"
DEFAULT_COLOR = "#2563EB"
DEFAULT_THEME = "system"
THEMES = ("light", "dark", "system")
THEME_CHOICES = [("light", "Светлая"), ("dark", "Тёмная"), ("system", "Как в системе")]
LOGO_EXTENSIONS = ("png", "jpg", "jpeg", "webp")  # SVG запрещён: в нём может быть скрипт
LOGO_MAX_BYTES = 1024 * 1024
HOST_MAX_LENGTH = 255
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

PLATFORM_DEFAULTS = {
    "app_name": PLATFORM_APP_NAME,
    "logo_url": None,
    "primary_color": DEFAULT_COLOR,
    "theme": DEFAULT_THEME,
}


def validate_color(value: str) -> None:
    if not COLOR_RE.match(value or ""):
        raise ValidationError("Цвет задаётся как #RRGGBB", code="invalid_color")


def _sniff(head: bytes) -> str | None:
    """Формат по первым байтам файла (расширению и Content-Type верить нельзя)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def validate_logo(file) -> None:
    """Расширение png/jpg/jpeg/webp, подпись файла совпадает с расширением, размер до 1 МБ."""
    name = getattr(file, "name", "") or ""
    ext = PurePosixPath(name).suffix.lower().lstrip(".")
    if ext not in LOGO_EXTENSIONS:
        raise ValidationError("Логотип: допустимы png, jpg, jpeg и webp (SVG запрещён)")
    if file.size > LOGO_MAX_BYTES:
        raise ValidationError("Логотип: размер файла не более 1 МБ")
    if file.size == 0:
        raise ValidationError("Логотип: файл пуст")
    position = file.tell() if hasattr(file, "tell") else 0
    file.seek(0)
    head = file.read(12)
    file.seek(position if position else 0)
    kind = _sniff(head)
    if kind is None or kind != ("jpeg" if ext in ("jpg", "jpeg") else ext):
        raise ValidationError("Логотип: содержимое файла не соответствует его расширению")


def logo_upload_to(instance, filename: str) -> str:
    """branding/<случайный каталог>/<случайное имя>.<расширение>.

    Ни id компании, ни имя файла клиента в пути не используются (публичный URL)."""
    ext = PurePosixPath(filename).suffix.lower().lstrip(".")
    if ext not in LOGO_EXTENSIONS:
        raise ValidationError("Логотип: недопустимое расширение")
    return f"branding/{uuid.uuid4().hex}/{uuid.uuid4().hex}.{ext}"


def normalize_host(raw: str) -> str:
    """Хост из ?host=: нижний регистр, без пробелов, порта и точки в конце."""
    host = (raw or "").strip().lower()
    if host.startswith("["):  # IPv6 в скобках
        host = host.split("]", 1)[0] + "]"
    elif host.count(":") == 1:
        name, port = host.split(":", 1)
        if port.isascii() and port.isdigit():  # «хост:порт»; «хост:abc» - мусор, не совпадёт
            host = name
    return host.rstrip(".")


def logo_url(branding, request) -> str | None:
    if not branding.logo:
        return None
    return request.build_absolute_uri(branding.logo.url)


def branding_payload(branding, request) -> dict:
    """Публичные поля оформления компании (без id и прочего)."""
    return {
        "app_name": branding.app_name,
        "logo_url": logo_url(branding, request),
        "primary_color": branding.primary_color,
        "theme": branding.theme,
    }


def branding_for_host(raw_host: str, request) -> dict:
    """Оформление по custom_domain; нет совпадения или пустой хост - значения платформы."""
    from .models import CompanyBranding

    host = normalize_host(raw_host)
    if not host:
        return dict(PLATFORM_DEFAULTS)
    branding = CompanyBranding.objects.filter(custom_domain=host).first()
    if branding is None:
        return dict(PLATFORM_DEFAULTS)
    payload = branding_payload(branding, request)
    payload["app_name"] = payload["app_name"] or PLATFORM_APP_NAME
    return payload
