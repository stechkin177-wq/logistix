"""Рукописный отчётный лист: разбор значений, сверка двух чтений, проверки, API."""

import json
from decimal import Decimal

import pytest

from apps.core.tenancy import tenant_context
from apps.ocr import gemini, handwriting
from apps.ocr.models import OcrSettings
from apps.ocr.tests.helpers import BASE, JPEG, upload

pytestmark = pytest.mark.django_db

SHEET = {
    "page_type": "main",
    "header": {"driver": "Иванов", "start_odometer_km": "100000", "end_odometer_km": "104500"},
    "cash_remaining": {"KZT": "50 000", "RUB": None},
    "fuel_tractor": [
        {"date": "20.11", "liters": "100", "price": "310", "amount": "31000"},
        {"date": "21.11", "liters": "120", "price": "310", "amount": "40000"},
    ],
    "transfers": [{"date": "19.11", "amount": "60+30", "currency": "KZT", "description": "аванс"}],
    "uncertain": ["fuel_tractor[1].liters"],
}


def test_parse_number_variants():
    assert handwriting.parse_number("1 234,5") == (Decimal("1234.5"), False)
    assert handwriting.parse_number("60+30") == (Decimal("90"), True)
    assert handwriting.parse_number("abc") == (None, False)
    assert handwriting.parse_number(None) == (None, False)


def test_parse_date_without_year_picks_past():
    from datetime import date

    today = date(2026, 11, 20)
    assert handwriting.parse_date("22.07", today) == "2026-07-22"
    assert handwriting.parse_date("25.12", today) == "2025-12-25"  # не из будущего
    assert handwriting.parse_date("мусор", today) == ""


def test_compare_readings_finds_disagreement_and_missing_row():
    first = {
        "fuel_tractor": [{"liters": "100"}, {"liters": "120"}],
        "header": {"end_odometer_km": 5},
    }
    second = {
        "fuel_tractor": [{"liters": "100"}, {"liters": "126"}],
        "header": {"end_odometer_km": 6},
    }
    cross = handwriting.compare_readings(first, second)
    assert cross["alt"] == {"fuel_tractor[1].liters": "126", "header.end_odometer_km": "6"}
    shifted = handwriting.compare_readings(first, {"fuel_tractor": [{"liters": "100"}]})
    assert "fuel_tractor[1].liters" in shifted["missing"] and shifted["notes"]
    assert "header.end_odometer_km" in shifted["missing"]  # шапки во втором чтении нет


def test_check_values_flags_rules():
    flags = handwriting.check_values(SHEET)
    assert (
        "fuel_tractor[1].liters" in flags and "fuel_tractor[1].amount" in flags
    )  # 120 x 310 != 40000
    assert "fuel_tractor[0].liters" not in flags
    assert "transfers[0].amount" in flags  # выражение 60+30
    backwards = handwriting.check_values(
        {"header": {"start_odometer_km": 10, "end_odometer_km": 5}}
    )
    assert "header.end_odometer_km" in backwards and "header.start_odometer_km" in backwards


def test_build_page_merges_model_uncertainty_and_cross():
    page = handwriting.build_page(
        SHEET,
        {"alt": {"header.end_odometer_km": "104600"}, "missing": [], "notes": ["n"]},
        [],
        ["m1"],
    )
    assert "Нейросеть не уверена в этом значении" in page["flags"]["fuel_tractor[1].liters"]
    assert page["alt"] == {"header.end_odometer_km": "104600"}
    assert "uncertain" not in page["raw"] and page["notes"] == ["n"]


def fake_reader(by_model):
    def reader(data, content_type, model, api_key, timeout=24, retries=0):
        value = by_model[model]
        if isinstance(value, Exception):
            raise value
        return value

    return reader


def test_read_sheet_two_models_and_fallbacks(monkeypatch):
    cfg = handwriting.HandwritingConfig(api_key="k", model="a", check_model="b")
    other = json.loads(json.dumps(SHEET))
    other["fuel_tractor"][0]["liters"] = "101"
    monkeypatch.setattr(handwriting, "read_report_sheet", fake_reader({"a": SHEET, "b": other}))
    page = handwriting.read_sheet(JPEG, "image/jpeg", cfg)
    assert page["models"] == ["a", "b"] and page["alt"] == {"fuel_tractor[0].liters": "101"}
    busy = gemini.GeminiError("занят", retryable=True)
    monkeypatch.setattr(handwriting, "read_report_sheet", fake_reader({"a": busy, "b": SHEET}))
    page = handwriting.read_sheet(JPEG, "image/jpeg", cfg)
    assert page["models"] == ["b"] and "без пересверки" in page["notes"][0]
    monkeypatch.setattr(handwriting, "read_report_sheet", fake_reader({"a": SHEET, "b": busy}))
    page = handwriting.read_sheet(JPEG, "image/jpeg", cfg)
    assert page["models"] == ["a"] and "пересверка не выполнена" in page["notes"][0]
    monkeypatch.setattr(handwriting, "read_report_sheet", fake_reader({"a": busy, "b": busy}))
    with pytest.raises(handwriting.HandwritingError):
        handwriting.read_sheet(JPEG, "image/jpeg", cfg)


def test_fallback_models_replace_busy_ones(monkeypatch):
    busy = gemini.GeminiError("занят", retryable=True)
    cfg = handwriting.HandwritingConfig(
        api_key="k", model="a", check_model="b", fallback_models=("c", "d")
    )
    monkeypatch.setattr(
        handwriting,
        "read_report_sheet",
        fake_reader({"a": busy, "b": busy, "c": SHEET, "d": SHEET}),
    )
    page = handwriting.read_sheet(JPEG, "image/jpeg", cfg)
    assert page["models"] == ["c", "d"]
    assert any("Основная модель недоступна" in n for n in page["notes"])
    # одна основная жива, вторую заменяет запасная
    monkeypatch.setattr(
        handwriting,
        "read_report_sheet",
        fake_reader({"a": SHEET, "b": busy, "c": SHEET, "d": busy}),
    )
    page = handwriting.read_sheet(JPEG, "image/jpeg", cfg)
    assert page["models"] == ["a", "c"] and any("пересверила «c»" in n for n in page["notes"])
    # все недоступны
    monkeypatch.setattr(handwriting, "read_report_sheet", fake_reader({m: busy for m in "abcd"}))
    with pytest.raises(handwriting.HandwritingError):
        handwriting.read_sheet(JPEG, "image/jpeg", cfg)


def test_gemini_error_hides_key(monkeypatch):
    import io
    import urllib.error

    body = {"error": {"message": "bad key SECRET123"}}

    def boom(request, timeout=0):
        raise urllib.error.HTTPError("u", 400, "x", {}, io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(gemini.GeminiError) as exc:
        gemini.generate_json("m", "SECRET123", [{"text": "x"}])
    assert "SECRET123" not in str(exc.value)


# --- API ---


def test_upload_report_sheet_without_key_fails_clearly(oco):
    _, _, api = oco
    r = upload(api, doc_type="report_sheet")
    assert r.status_code == 201 and r.json()["status"] == "failed"
    assert "Gemini" in r.json()["error"]


def test_upload_report_sheet_reads_with_gemini(oco, monkeypatch):
    _, _, api = oco
    api.put(f"{BASE}settings/", {"gemini_key": "AIza-secret"}, format="json")
    monkeypatch.setattr(
        handwriting,
        "read_report_sheet",
        fake_reader({"gemini-3.8-flash": SHEET, "gemini-3.6-flash": SHEET}),
    )
    body = upload(api, doc_type="report_sheet").json()
    assert body["status"] == "done" and body["engine"] == "gemini"
    assert body["sheet"]["page_type"] == "main" and body["sheet"]["flags"]
    assert body["fields"] == {}


def test_gemini_settings_write_only_and_validated(oco):
    company, _, api = oco
    r = api.put(
        f"{BASE}settings/",
        {
            "gemini_key": "AIza-secret",
            "handwriting_model": "gemini-x",
            "handwriting_crosscheck": False,
        },
        format="json",
    )
    body = r.json()
    assert (
        r.status_code == 200 and body["has_gemini_key"] and body["handwriting_model"] == "gemini-x"
    )
    assert "AIza-secret" not in json.dumps(body) and body["handwriting_crosscheck"] is False
    with tenant_context(company.id):
        assert "AIza-secret" not in OcrSettings.objects.get().gemini_key_enc
    bad = api.put(f"{BASE}settings/", {"handwriting_model": "bad model!"}, format="json")
    assert bad.status_code == 400


def test_gemini_test_endpoint(oco, monkeypatch):
    _, _, api = oco
    assert api.post(f"{BASE}settings/test-gemini/").json()["ok"] is False  # ключа нет
    api.put(f"{BASE}settings/", {"gemini_key": "k"}, format="json")
    calls = []
    monkeypatch.setattr(
        gemini, "check_key", lambda model, key, data, ct: calls.append(model) or "ok"
    )
    body = api.post(f"{BASE}settings/test-gemini/").json()
    assert body["ok"] is True and sorted(calls) == ["gemini-3.6-flash", "gemini-3.8-flash"]


def test_gemini_test_uses_models_from_the_form_not_only_saved(oco, monkeypatch):
    _, _, api = oco
    api.put(f"{BASE}settings/", {"gemini_key": "k"}, format="json")
    calls = []
    monkeypatch.setattr(
        gemini, "check_key", lambda model, key, data, ct: calls.append(model) or "ok"
    )
    body = api.post(
        f"{BASE}settings/test-gemini/",
        {"model": "gemini-x", "check_model": "gemini-y"},
        format="json",
    ).json()
    assert sorted(calls) == ["gemini-x", "gemini-y"] and set(body["models"]) == {
        "gemini-x",
        "gemini-y",
    }
    bad = api.post(f"{BASE}settings/test-gemini/", {"model": "bad model!"}, format="json")
    assert bad.status_code == 400


def test_list_models_filters_and_sorts_newest_first(monkeypatch):
    payload = {
        "models": [
            {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {
                "name": "models/gemini-3.5-flash-lite",
                "supportedGenerationMethods": ["generateContent"],
            },
            {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
            {
                "name": "models/gemini-3.8-flash-tts",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-3-flash-preview",
                "supportedGenerationMethods": ["generateContent"],
            },
            {"name": "models/gemma-3", "supportedGenerationMethods": ["generateContent"]},
        ]
    }

    class Resp:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda r, timeout=0: Resp())
    assert gemini.list_models("k") == [
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
    ]


def test_gemini_models_endpoint(oco, monkeypatch):
    _, _, api = oco
    assert api.get(f"{BASE}settings/gemini-models/").json()["error"] != ""  # ключа нет
    api.put(f"{BASE}settings/", {"gemini_key": "k"}, format="json")
    monkeypatch.setattr(gemini, "list_models", lambda key, timeout=20: ["gemini-3.8-flash"])
    body = api.get(f"{BASE}settings/gemini-models/").json()
    assert body == {"models": ["gemini-3.8-flash"], "error": ""}
