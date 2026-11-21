"""Рабочее место распознавания: типы документов компании, группы по водителям и машинам, архив,
фото, сверка с фото, очистка фото из архива."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.ocr import services
from apps.ocr.models import OcrFile, ScannedDocument
from apps.ocr.tests.helpers import BASE, JPEG, upload

pytestmark = pytest.mark.django_db


def test_doc_types_are_seeded_and_manageable(oco):
    company, _, api = oco
    rows = api.get(f"{BASE}doc-types/").json()
    assert {r["code"] for r in rows} >= {"fuel_receipt", "report_sheet", "other"}
    made = api.post(
        f"{BASE}doc-types/",
        {"name": "Акт сверки", "handler": "generic", "driver_visible": False},
        format="json",
    )
    assert made.status_code == 201 and made.json()["code"]
    assert (
        api.post(
            f"{BASE}doc-types/", {"name": " ", "handler": "generic"}, format="json"
        ).status_code
        == 400
    )
    code, row_id = made.json()["code"], made.json()["id"]
    assert api.delete(f"{BASE}doc-types/{row_id}/").status_code == 204  # документов нет - удалён
    assert upload(api, doc_type=code).status_code == 400  # неизвестный тип


def test_used_doc_type_is_deactivated_not_deleted(oco):
    _, _, api = oco
    made = api.post(
        f"{BASE}doc-types/", {"name": "Спец", "handler": "generic"}, format="json"
    ).json()
    assert upload(api, doc_type=made["code"]).status_code == 201
    out = api.delete(f"{BASE}doc-types/{made['id']}/")
    assert out.status_code == 200 and out.json() == {"deactivated": True}
    rows = {x["code"]: x for x in api.get(f"{BASE}doc-types/").json()}
    assert rows[made["code"]]["is_active"] is False and rows[made["code"]]["used"] == 1
    assert upload(api, doc_type=made["code"]).status_code == 400  # отключённый тип не принимается


def test_office_archive_image_review_and_groups(oco):
    _, _, api = oco
    doc = upload(api, doc_type="fuel_receipt").json()
    img = api.get(f"{BASE}documents/{doc['id']}/image/")
    assert img.status_code == 200 and img["Content-Type"] == "image/jpeg" and img.content == JPEG
    saved = api.post(
        f"{BASE}documents/{doc['id']}/save-review/",
        {"edits": {"amount": " 100 "}, "checked": ["amount", "amount", "date"], "done": True},
        format="json",
    ).json()
    assert saved["review"] == {"edits": {"amount": "100"}, "checked": ["amount", "date"]}
    assert saved["reviewed_at"] is not None
    bad = api.post(f"{BASE}documents/{doc['id']}/save-review/", {"edits": [1]}, format="json")
    assert bad.status_code == 400
    # архив: из обычного списка уходит, в архивном виден, возвращается обратно
    assert api.post(f"{BASE}documents/{doc['id']}/archive/", {}, format="json").json()[
        "archived_at"
    ]
    assert api.get(f"{BASE}documents/").json()["count"] == 0
    assert api.get(f"{BASE}documents/?archived=true").json()["count"] == 1
    api.post(f"{BASE}documents/{doc['id']}/archive/", {"archived": False}, format="json")
    assert api.get(f"{BASE}documents/").json()["count"] == 1
    # группы: документ без водителя - группа 0
    groups = api.get(f"{BASE}documents/groups/?by=driver").json()["results"]
    assert groups == [{"id": 0, "name": "", "total": 1, "pending": 0}]
    assert api.get(f"{BASE}documents/groups/?by=other").status_code == 400
    assert api.get(f"{BASE}documents/?driver=0").json()["count"] == 1
    assert api.get(f"{BASE}documents/?driver=999").json()["count"] == 0
    assert api.get(f"{BASE}documents/?vehicle=abc").json()["count"] == 0


def test_purge_removes_only_old_archived_photos(oco):
    company, _, api = oco
    old = upload(api, doc_type="fuel_receipt").json()["id"]
    fresh = upload(api, doc_type="fuel_receipt").json()["id"]
    live = upload(api, doc_type="fuel_receipt").json()["id"]
    now = timezone.now()
    with tenant_context(company.id):
        ScannedDocument.objects.filter(pk=old).update(archived_at=now - timedelta(days=181))
        ScannedDocument.objects.filter(pk=fresh).update(archived_at=now - timedelta(days=10))
        assert services.purge_old_files() == 1
        left = set(OcrFile.objects.values_list("document_id", flat=True))
    assert left == {fresh, live}
    # запись документа и данные остаются, фото больше нет
    assert api.get(f"{BASE}documents/{old}/image/").status_code == 404
    assert api.get(f"{BASE}documents/?archived=true").json()["count"] == 2


def test_cron_purge_requires_secret(oco, settings):
    _, _, api = oco
    from rest_framework.test import APIClient

    anon = APIClient()
    settings.CRON_SECRET = ""
    assert anon.get(f"{BASE}cron/purge/").status_code == 403
    settings.CRON_SECRET = "s3cret"
    assert anon.get(f"{BASE}cron/purge/", HTTP_AUTHORIZATION="Bearer wrong").status_code == 403
    ok = anon.get(f"{BASE}cron/purge/", HTTP_AUTHORIZATION="Bearer s3cret")
    assert ok.status_code == 200 and "purged" in ok.json()
