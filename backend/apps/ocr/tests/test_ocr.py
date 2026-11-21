"""Модуль ocr: движки с запасным вариантом, разбор полей чека, шифрование ключей, API, лимит."""

import json
from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.core.api.auth import issue_tokens
from apps.core.models import Membership, Role, User
from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.ocr import crypto, engines, fields, services, storage
from apps.ocr.models import OcrSettings, ScannedDocument
from apps.ocr.tests.helpers import BASE, JPEG, _n, ocr_company, upload

pytestmark = pytest.mark.django_db

RECEIPT = """АЗС Helios
18.11.2026 14:05
ДТ 886AIA14
Количество 120,50 л
Цена 310,00
ИТОГО 37355,00
"""


def api_with_role(company, role_name):
    user = User.objects.create_user(email=f"o{next(_n)}@ocr.kz", password="Str0ng-pass-91")
    with tenant_context(company.id):
        role = Role.objects.get(name=role_name)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return api


class FakeEngine:
    """Подмена движка: возвращает текст или бросает OcrError, по сети не ходит."""

    def __init__(self, text="", error="", is_available=True):
        self.text, self.error, self.is_available = text, error, is_available

    def __call__(self, key=""):
        self.key = key
        return self

    def available(self):
        return self.is_available

    def recognize(self, data, content_type):
        if self.error:
            raise engines.OcrError(self.error)
        return self.text


@pytest.fixture
def fake(monkeypatch):
    def install(**by_name):
        table = dict(engines.ENGINES)
        table.update(by_name)
        monkeypatch.setattr(engines, "ENGINES", table)

    return install


# --- шифрование ---


def test_crypto_roundtrip_and_hides_plaintext():
    token = crypto.encrypt("secret-key-123")
    assert "secret-key-123" not in token and crypto.decrypt(token) == "secret-key-123"
    assert crypto.decrypt("") == ""


# --- движки и запасной вариант ---


def test_chain_puts_selected_first_then_available_fallbacks(fake):
    fake(tesseract=FakeEngine(is_available=False))
    cfg = engines.Config("ocr_space", google_vision_key="g", ocr_space_key="o")
    assert engines.chain(cfg) == ["ocr_space", "google_vision"]
    assert engines.chain(engines.Config("ocr_space", ocr_space_key="o", fallback=False)) == [
        "ocr_space"
    ]


def test_fallback_used_when_first_engine_fails(fake):
    fake(
        ocr_space=FakeEngine(error="OCR.space недоступен"),
        google_vision=FakeEngine(text="привет"),
        tesseract=FakeEngine(is_available=False),
    )
    cfg = engines.Config("ocr_space", google_vision_key="g", ocr_space_key="o")
    assert engines.recognize(JPEG, "image/jpeg", cfg) == ("привет", "google_vision")


def test_all_engines_failing_gathers_messages(fake):
    fake(
        ocr_space=FakeEngine(error="первый сбой"),
        google_vision=FakeEngine(error="второй сбой"),
        tesseract=FakeEngine(is_available=False),
    )
    cfg = engines.Config("ocr_space", google_vision_key="g", ocr_space_key="o")
    with pytest.raises(engines.OcrError) as exc:
        engines.recognize(JPEG, "image/jpeg", cfg)
    assert "первый сбой" in str(exc.value) and "второй сбой" in str(exc.value)


def test_real_engines_reject_missing_key_and_big_file():
    with pytest.raises(engines.OcrError):
        engines.OcrSpace("").recognize(JPEG, "image/jpeg")
    with pytest.raises(engines.OcrError):
        engines.OcrSpace("k").recognize(b"0" * 1_000_001, "image/jpeg")
    with pytest.raises(engines.OcrError):
        engines.GoogleVision("").recognize(JPEG, "image/jpeg")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_google_vision_parses_response_and_key_stays_out_of_errors(monkeypatch):
    seen = {}

    def fake_open(request, timeout=0):
        seen["url"] = request.full_url
        return FakeResponse({"responses": [{"fullTextAnnotation": {"text": "ИТОГО 100"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    assert engines.GoogleVision("KEY").recognize(JPEG, "image/jpeg") == "ИТОГО 100"

    def boom(request, timeout=0):
        raise OSError("connection reset KEY")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(engines.OcrError) as exc:
        engines.GoogleVision("KEY").recognize(JPEG, "image/jpeg")
    assert "KEY" not in str(exc.value)


def test_ocr_space_retries_with_mode_2(monkeypatch):
    calls = []

    def fake_open(request, timeout=0):
        calls.append(request.data)
        if len(calls) == 1:
            return FakeResponse({"IsErroredOnProcessing": True, "ErrorMessage": ["bad"]})
        return FakeResponse({"ParsedResults": [{"ParsedText": "текст"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    assert engines.OcrSpace("k").recognize(JPEG, "image/jpeg") == "текст"
    assert len(calls) == 2 and b"rus" in calls[1]


def test_check_engine_reports_error_without_key():
    assert engines.check_engine("ocr_space", engines.Config(engine="ocr_space")) != ""


# --- разбор полей ---


def test_parse_fuel_receipt():
    got = fields.parse_fields(RECEIPT, "fuel_receipt", today=date(2026, 11, 20))
    assert got["date"] == "2026-11-18"
    assert got["amount"] == "37355.00" or got["amount"] == "37355"
    assert got["liters"].startswith("120.5")
    assert got["fuel_type"] == "diesel" and got["plate"] == "886AIA14"


def test_parse_date_rejects_future_and_old():
    today = date(2026, 11, 20)
    assert fields.parse_date("01.01.2030", today) is None
    assert fields.parse_date("01.01.2010", today) is None
    assert fields.parse_date("20.11.2026", today) == "2026-11-20"


def test_parse_plate_normalizes_cyrillic():
    assert fields.parse_plate("номер 886АІА14".replace("І", "I")) == "886AIA14"


def test_amount_falls_back_to_largest_number():
    got = fields.parse_fields("хлеб 120\nмолоко 340\n", "other", today=date(2026, 11, 20))
    assert got["amount"].startswith("340")


# --- сервис и API ---


def test_upload_creates_document_with_fields(oco, fake, monkeypatch):
    company, _, api = oco
    fake(ocr_space=FakeEngine(text=RECEIPT), tesseract=FakeEngine(is_available=False))
    monkeypatch.setattr(
        services, "env_defaults", lambda: {"google_vision_key": "", "ocr_space_key": "k"}
    )
    r = upload(api, doc_type="fuel_receipt")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "done" and body["engine"] == "ocr_space"
    assert body["fields"]["fuel_type"] == "diesel" and body["has_file"]
    listing = api.get(f"{BASE}documents/?status=done").json()
    assert listing["count"] == 1


def test_failed_recognition_is_saved_as_failed(oco, fake, monkeypatch):
    _, _, api = oco
    fake(ocr_space=FakeEngine(error="сбой"), tesseract=FakeEngine(is_available=False))
    r = upload(api)
    assert r.status_code == 201
    assert r.json()["status"] == "failed" and "сбой" in r.json()["error"]


def test_upload_validation(oco):
    _, _, api = oco
    assert api.post(f"{BASE}documents/", {}, format="multipart").status_code == 400
    assert upload(api, data=b"%PDF-1.4 not an image").status_code == 400
    assert upload(api, data=JPEG + b"0" * 4_000_001).status_code == 400
    assert upload(api, doc_type="weird").status_code == 400


def test_patch_fields_validated_and_cleaned(oco, fake):
    _, _, api = oco
    fake(ocr_space=FakeEngine(text=RECEIPT), tesseract=FakeEngine(is_available=False))
    doc_id = upload(api, doc_type="fuel_receipt").json()["id"]
    url = f"{BASE}documents/{doc_id}/"
    ok = api.patch(url, {"fields": {"liters": " 100 ", "note": ""}}, format="json")
    assert ok.status_code == 200 and ok.json()["fields"] == {"liters": "100"}
    assert api.patch(url, {"fields": {"hack": "x"}}, format="json").status_code == 400
    assert api.patch(url, {"fields": {"liters": 5}}, format="json").status_code == 400
    assert api.patch(url, {"text": "подмена"}, format="json").json()["text"] != "подмена"


def test_delete_document(oco, fake):
    company, _, api = oco
    fake(ocr_space=FakeEngine(text="x"), tesseract=FakeEngine(is_available=False))
    doc_id = upload(api).json()["id"]
    assert api.delete(f"{BASE}documents/{doc_id}/").status_code == 204
    with tenant_context(company.id):
        assert ScannedDocument.objects.count() == 0


def test_storage_saves_original_and_deletes_with_document(oco, fake, monkeypatch, settings):
    _, _, api = oco
    settings.OCR_STORAGE_URL = "https://x.supabase.co"
    settings.OCR_STORAGE_KEY = "svc"
    settings.OCR_STORAGE_BUCKET = "b"
    stored = {}
    monkeypatch.setattr(storage, "put", lambda key, data, ct: stored.update({key: data}))
    monkeypatch.setattr(storage, "signed_url", lambda key, expires=300: f"https://x/{key}")
    monkeypatch.setattr(storage, "delete", lambda key: stored.pop(key, None))
    fake(ocr_space=FakeEngine(text="x"), tesseract=FakeEngine(is_available=False))
    body = upload(api).json()
    assert body["has_file"] and len(stored) == 1
    api.delete(f"{BASE}documents/{body['id']}/")
    assert stored == {}


def test_documents_are_tenant_isolated(oco, make_company, fake):
    _, _, api = oco
    fake(ocr_space=FakeEngine(text="x"), tesseract=FakeEngine(is_available=False))
    doc_id = upload(api).json()["id"]
    _, _, other = ocr_company(make_company, "Other")
    assert other.get(f"{BASE}documents/").json()["count"] == 0
    assert other.get(f"{BASE}documents/{doc_id}/").status_code == 404


# --- настройки ---


def test_settings_keys_are_write_only_and_encrypted(oco):
    company, _, api = oco
    r = api.put(
        f"{BASE}settings/",
        {"engine": "google_vision", "google_vision_key": "GV-SECRET", "auto_fallback": False},
        format="json",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "google_vision" and body["has_google_vision_key"] is True
    assert "GV-SECRET" not in json.dumps(body) and "google_vision_key" not in body
    with tenant_context(company.id):
        row = OcrSettings.objects.get()
    assert "GV-SECRET" not in row.google_vision_key_enc and not row.auto_fallback
    again = api.put(f"{BASE}settings/", {"google_vision_key": ""}, format="json").json()
    assert again["has_google_vision_key"] is True  # пустой ключ - без изменения
    assert api.put(f"{BASE}settings/", {"engine": "nope"}, format="json").status_code == 400


def test_settings_test_endpoint(oco, fake):
    _, _, api = oco
    api.put(f"{BASE}settings/", {"ocr_space_key": "k"}, format="json")
    fake(ocr_space=FakeEngine(text="ok"), tesseract=FakeEngine(is_available=False))
    results = api.post(f"{BASE}settings/test/").json()["results"]
    assert "ocr_space" in results and "tesseract" not in results


# --- права, модуль, лимит ---


def test_module_off_and_permissions(oco, make_company):
    company, _, api = oco
    mech = api_with_role(company, "Механик")
    assert mech.get(f"{BASE}documents/").status_code == 200
    assert mech.put(f"{BASE}settings/", {"engine": "tesseract"}, format="json").status_code == 403
    watcher = api_with_role(company, "Наблюдатель")
    assert watcher.get(f"{BASE}documents/").status_code == 200
    assert upload(watcher).status_code == 403
    driver = api_with_role(company, "Водитель")
    assert driver.get(f"{BASE}documents/").status_code == 403
    set_company_modules(company, ["documents"])
    assert api.get(f"{BASE}documents/").status_code == 403


def test_monthly_limit_blocks_before_recognition(oco, fake):
    company, _, api = oco
    plan = company.subscription.plan
    plan.limits = {**(plan.limits or {}), "max_ocr_per_month": 1}
    plan.save()
    called = []

    class Counting(FakeEngine):
        def recognize(self, data, content_type):
            called.append(1)
            return "x"

    fake(ocr_space=Counting(), tesseract=FakeEngine(is_available=False))
    assert upload(api).status_code == 201
    second = upload(api)
    assert second.status_code == 402 and second.json()["limit_code"] == "max_ocr_per_month"
    assert len(called) == 1


# --- переключение при исчерпании бесплатного лимита Google ---


def test_google_switches_to_ocr_space_when_monthly_limit_reached(oco, fake, settings):
    company, _, api = oco
    settings.OCR_GOOGLE_MONTHLY_LIMIT = 2
    api.put(
        f"{BASE}settings/",
        {"engine": "google_vision", "google_vision_key": "g", "ocr_space_key": "o"},
        format="json",
    )
    used = []

    class Named(FakeEngine):
        def __init__(self, name):
            super().__init__(text=name)

        def recognize(self, data, content_type):
            used.append(self.text)
            return self.text

    fake(google_vision=Named("google_vision"), ocr_space=Named("ocr_space"),
         tesseract=FakeEngine(is_available=False))  # fmt: skip
    for _ in range(2):
        assert upload(api).json()["engine"] == "google_vision"
    third = upload(api).json()
    assert third["engine"] == "ocr_space"  # порог достигнут: Google пропущен
    assert used == ["google_vision", "google_vision", "ocr_space"]
    body = api.get(f"{BASE}settings/").json()
    assert body["google_used"] == 2 and body["google_limit"] == 2


def test_google_error_shows_reason(monkeypatch):
    import io
    import urllib.error

    body = {"error": {"message": "Permission denied", "status": "PERMISSION_DENIED",
                      "details": [{"reason": "SERVICE_DISABLED"}]}}  # fmt: skip

    def boom(request, timeout=0):
        raise urllib.error.HTTPError("u", 403, "x", {}, io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(engines.OcrError) as exc:
        engines.GoogleVision("k").recognize(JPEG, "image/jpeg")
    assert "SERVICE_DISABLED" in str(exc.value) and "PERMISSION_DENIED" in str(exc.value)
