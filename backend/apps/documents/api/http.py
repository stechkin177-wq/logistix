"""Общие вещи API документов: ответ-файл и лимит запросов на компанию."""

import re
from urllib.parse import quote

from django.http import HttpResponse
from rest_framework.throttling import SimpleRateThrottle

_ASCII_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def file_response(content: bytes, content_type: str, filename: str) -> HttpResponse:
    """Файл-вложение: ASCII-запасное имя и filename*=UTF-8'' (RFC 6266), без кэширования."""
    fallback = _ASCII_UNSAFE.sub("_", filename).strip("_") or "document"
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = (
        f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class CompanyThrottle(SimpleRateThrottle):
    """Лимит запросов на КОМПАНИЮ (а не на пользователя или IP): счётчик в кэше.

    Применяется после проверки прав, поэтому членство и компания уже известны.
    """

    def get_cache_key(self, request, view):
        membership = getattr(request, "membership", None)
        if membership is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": membership.company_id}


class TemplateUploadThrottle(CompanyThrottle):
    scope = "document_upload"


class PdfDownloadThrottle(CompanyThrottle):
    scope = "document_pdf"
