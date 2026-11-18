"""Шифрование токена Wialon (Fernet). Ключ - GPS_ENCRYPTION_KEY; без него выводится из SECRET_KEY.

Свой ключ в окружении рекомендуется: утечка SECRET_KEY тогда не раскрывает токены."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    raw = getattr(settings, "GPS_ENCRYPTION_KEY", "") or ""
    if raw:
        try:
            return Fernet(raw.encode())
        except ValueError:
            pass  # не ключ Fernet: берём как парольную фразу
        material = raw
    else:
        material = settings.SECRET_KEY
    digest = hashlib.sha256(f"logistix-gps:{material}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""  # ключ сменили: токен нужно ввести заново
