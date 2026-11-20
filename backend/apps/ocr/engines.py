"""Движки распознавания текста с запасным вариантом: Google Cloud Vision, OCR.space, Tesseract.

Перенесено из truck365 без сторонних библиотек (только urllib и subprocess): картинку сжимает
приложение до отправки, сервер принимает готовый JPEG/PNG. Ключи в тексты ошибок не попадают."""

import base64
import json
import logging
import shutil
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 40
OCR_SPACE_MAX_BYTES = 1_000_000  # бесплатный план OCR.space не принимает файлы больше 1 МБ
GOOGLE_VISION_MAX_BYTES = 10_000_000
GOOGLE_VISION = "google_vision"
LABELS = {
    "google_vision": "Google Cloud Vision",
    "ocr_space": "OCR.space",
    "tesseract": "Tesseract (локальный)",
}
FALLBACK_ORDER = ("google_vision", "ocr_space", "tesseract")


class OcrError(Exception):
    """Сообщение безопасно показывать пользователю (ключей в нём нет)."""


def _google_detail(error: dict) -> str:
    """Сообщение Google с кодом причины (например SERVICE_DISABLED, BILLING_DISABLED,
    API_KEY_SERVICE_BLOCKED): по нему видно, что чинить."""
    reasons = [
        d.get("reason")
        for d in error.get("details") or []
        if isinstance(d, dict) and d.get("reason")
    ]
    parts = [str(error.get("message", "")), str(error.get("status", "")), *map(str, reasons)]
    return " | ".join(dict.fromkeys(p for p in parts if p))


def _http(request: urllib.request.Request, name: str) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - https, фиксированные адреса
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            error = body.get("error") if isinstance(body, dict) else None
            detail = _google_detail(error) if isinstance(error, dict) else ""
        except (ValueError, OSError):
            pass
        raise OcrError(f"{LABELS[name]} вернул {exc.code}: {detail[:200]}".rstrip(": ")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OcrError(f"{LABELS[name]} недоступен: {type(exc).__name__}") from None
    except ValueError:
        raise OcrError(f"{LABELS[name]} вернул не JSON") from None


class GoogleVision:
    name = "google_vision"

    def __init__(self, key: str):
        self.key = key

    def available(self) -> bool:
        return bool(self.key)

    def recognize(self, data: bytes, content_type: str) -> str:
        if not self.key:
            raise OcrError("Не задан ключ Google Vision.")
        if len(data) > GOOGLE_VISION_MAX_BYTES:
            raise OcrError("Google Vision: файл больше 10 МБ.")
        body = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(data).decode("ascii")},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    "imageContext": {"languageHints": ["ru", "en"]},
                }
            ]
        }
        request = urllib.request.Request(  # noqa: S310
            "https://vision.googleapis.com/v1/images:annotate",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": self.key},
            method="POST",
        )
        result = (_http(request, self.name).get("responses") or [{}])[0]
        if "error" in result:
            raise OcrError(f"Google Vision: {str(result['error'].get('message', 'ошибка'))[:200]}")
        return (result.get("fullTextAnnotation") or {}).get("text", "")


def _multipart(fields: dict, file_field: str, filename: str, content_type: str, data: bytes):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            ).encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class OcrSpace:
    """OCR.space: режим 3 (сам определяет кириллицу и латиницу); при сбое режим 2 с русским."""

    name = "ocr_space"

    def __init__(self, key: str):
        self.key = key

    def available(self) -> bool:
        return bool(self.key)

    def _parse(self, data: bytes, content_type: str, mode: str, language: str | None) -> str:
        fields = {"apikey": self.key, "isOverlayRequired": "false", "OCREngine": mode}
        if language:
            fields["language"] = language
        ext = "png" if content_type == "image/png" else "jpg"
        body, header = _multipart(fields, "file", f"page.{ext}", content_type, data)
        request = urllib.request.Request(  # noqa: S310
            "https://api.ocr.space/parse/image",
            data=body,
            headers={"Content-Type": header},
            method="POST",
        )
        result = _http(request, self.name)
        if result.get("IsErroredOnProcessing"):
            message = result.get("ErrorMessage")
            message = " ".join(message) if isinstance(message, list) else str(message or "ошибка")
            raise OcrError(f"OCR.space: {message[:200]}")
        return "\n".join(p.get("ParsedText", "") for p in result.get("ParsedResults") or [])

    def recognize(self, data: bytes, content_type: str) -> str:
        if not self.key:
            raise OcrError("Не задан ключ OCR.space.")
        if len(data) > OCR_SPACE_MAX_BYTES:
            raise OcrError("OCR.space: файл больше 1 МБ (бесплатный план). Сожмите фото.")
        try:
            return self._parse(data, content_type, "3", None)
        except OcrError as exc:
            logger.warning("OCR.space режим 3 не сработал (%s), пробуем режим 2", exc)
            return self._parse(data, content_type, "2", "rus")


class Tesseract:
    """Локальный Tesseract через командную строку (на Vercel его нет: движок будет недоступен)."""

    name = "tesseract"

    def __init__(self, key: str = ""):
        self.cmd = getattr(settings, "TESSERACT_CMD", "") or "tesseract"

    def available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def recognize(self, data: bytes, content_type: str) -> str:
        if not self.available():
            raise OcrError("Tesseract не установлен на сервере.")
        try:
            done = subprocess.run(  # noqa: S603
                [self.cmd, "stdin", "stdout", "-l", "rus+eng"],
                input=data, capture_output=True, timeout=TIMEOUT, check=True,
            )  # fmt: skip
        except subprocess.CalledProcessError as exc:
            raise OcrError(f"Tesseract: {exc.stderr.decode(errors='ignore')[:200]}") from None
        except subprocess.TimeoutExpired:
            raise OcrError("Tesseract: превышено время ожидания.") from None
        return done.stdout.decode("utf-8", errors="ignore")


ENGINES = {"google_vision": GoogleVision, "ocr_space": OcrSpace, "tesseract": Tesseract}


@dataclass(frozen=True)
class Config:
    """Выбранный движок, ключи компании и разрешение на запасные варианты."""

    engine: str
    google_vision_key: str = ""
    ocr_space_key: str = ""
    fallback: bool = True

    def key_for(self, name: str) -> str:
        return {"google_vision": self.google_vision_key, "ocr_space": self.ocr_space_key}.get(
            name, ""
        )


def chain(config: Config) -> list[str]:
    """Сначала выбранный движок; затем (если разрешено) остальные, которые могут сработать."""
    names = [config.engine]
    if config.fallback:
        for name in FALLBACK_ORDER:
            if name != config.engine and ENGINES[name](config.key_for(name)).available():
                names.append(name)
    return names


def recognize(data: bytes, content_type: str, config: Config) -> tuple[str, str]:
    """Распознаёт картинку: (текст, имя сработавшего движка). Все сбои - в одном OcrError."""
    problems = []
    for name in chain(config):
        try:
            return ENGINES[name](config.key_for(name)).recognize(data, content_type), name
        except OcrError as exc:
            logger.warning("OCR %s: %s", name, exc)
            problems.append(str(exc))
    raise OcrError(" | ".join(problems) or "Нет доступного движка распознавания.")


def _probe_png() -> bytes:
    """Белая картинка 8x8 в PNG для проверки ключа без реального документа."""
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xff" * 8 for _ in range(8))  # 8 строк: фильтр 0 + 8 серых пикселей
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


PROBE_PNG = _probe_png()


def check_engine(name: str, key: str) -> str:
    """'' если ключ принят и движок отвечает, иначе понятная причина (без ключа в тексте)."""
    engine = ENGINES[name](key)
    if not engine.available():
        return "нет ключа" if name != "tesseract" else "Tesseract не установлен на сервере"
    try:
        engine.recognize(PROBE_PNG, "image/png")
    except OcrError as exc:
        text = str(exc)
        # «пустая картинка» для проверки ключа - не ошибка ключа
        if any(w in text.lower() for w in ("no text", "empty", "пуст", "e500", "e301")):
            return ""
        return text
    return ""
