"""TOTP (RFC 6238) на стандартной библиотеке: без внешних сервисов и новых зависимостей.

Шаг 30 секунд, 6 цифр, SHA-1 (совместимо с Google Authenticator, Aegis, FreeOTP и др.).
Каждый код принимается один раз: последний использованный шаг хранится у пользователя.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
ISSUER = "LogistiX"


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_for(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def verify(secret: str, code: str, last_step: int = 0, now: float | None = None, window: int = 1):
    """Номер шага при верном коде (допуск ±window шагов, шаг не старше last_step), иначе None."""
    cleaned = (code or "").replace(" ", "").strip()
    if len(cleaned) != DIGITS or not cleaned.isascii() or not cleaned.isdigit():
        return None
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    for step in range(current - window, current + window + 1):
        if step > last_step and hmac.compare_digest(code_for(secret, step), cleaned):
            return step
    return None


def otpauth_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}"
