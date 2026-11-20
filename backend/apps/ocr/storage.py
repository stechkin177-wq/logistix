"""Хранилище оригиналов: Supabase Storage (бесплатный план) через REST, без сторонних библиотек.

Включается переменными OCR_STORAGE_URL (https://<проект>.supabase.co), OCR_STORAGE_KEY
(service role)
и OCR_STORAGE_BUCKET (приватный бакет). Без них оригинал не сохраняется (распознанный текст и поля
остаются): на Vercel нет постоянного диска."""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)
TIMEOUT = 30
EXT = {"image/jpeg": "jpg", "image/png": "png"}


class StorageError(Exception):
    pass


def configured() -> bool:
    return all(
        getattr(settings, name, "")
        for name in ("OCR_STORAGE_URL", "OCR_STORAGE_KEY", "OCR_STORAGE_BUCKET")
    )


def _base() -> str:
    return settings.OCR_STORAGE_URL.rstrip("/") + "/storage/v1"


def _call(
    method: str, path: str, *, data: bytes | None = None, headers: dict | None = None
) -> bytes:
    request = urllib.request.Request(  # noqa: S310 - адрес хранилища задаёт администратор сервера
        _base() + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {settings.OCR_STORAGE_KEY}",
            "apikey": settings.OCR_STORAGE_KEY,
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise StorageError(f"Хранилище ответило {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StorageError(f"Хранилище недоступно: {type(exc).__name__}") from None


def new_key(company_id: int, content_type: str) -> str:
    return f"{company_id}/{uuid.uuid4().hex}.{EXT.get(content_type, 'bin')}"


def put(key: str, data: bytes, content_type: str) -> None:
    path = f"/object/{settings.OCR_STORAGE_BUCKET}/{urllib.parse.quote(key)}"
    _call("POST", path, data=data, headers={"Content-Type": content_type, "x-upsert": "false"})


def signed_url(key: str, expires: int = 300) -> str:
    path = f"/object/sign/{settings.OCR_STORAGE_BUCKET}/{urllib.parse.quote(key)}"
    raw = _call(
        "POST", path, data=json.dumps({"expiresIn": expires}).encode(),
        headers={"Content-Type": "application/json"},
    )  # fmt: skip
    signed = json.loads(raw.decode()).get("signedURL", "")
    if not signed:
        raise StorageError("Хранилище не выдало ссылку")
    return _base() + signed if signed.startswith("/") else signed


def delete(key: str) -> None:
    try:
        _call("DELETE", f"/object/{settings.OCR_STORAGE_BUCKET}/{urllib.parse.quote(key)}")
    except StorageError as exc:
        logger.warning("Не удалось удалить оригинал %s: %s", key, exc)
