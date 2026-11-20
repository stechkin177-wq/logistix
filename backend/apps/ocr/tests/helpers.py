"""Общие помощники тестов модуля ocr."""

import itertools

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.billing.models import Plan
from apps.core.module_services import set_company_modules
from apps.ocr import engines

_n = itertools.count(1)
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = engines.PROBE_PNG
BASE = "/api/ocr/"


def ocr_company(make_company, name="OCR"):
    plan = Plan.objects.get(code="start")
    mods = list(plan.modules)
    for code in ("documents", "ocr"):
        if code not in mods:
            mods.append(code)
    Plan.objects.filter(code="start").update(modules=mods)
    company, admin, api = make_company(name, modules=["fleet"])
    set_company_modules(company, ["documents", "ocr"])
    return company, admin, api


def upload(api, data=JPEG, name="check.jpg", **extra):
    return api.post(
        f"{BASE}documents/",
        {"file": SimpleUploadedFile(name, data, content_type="image/jpeg"), **extra},
        format="multipart",
    )
