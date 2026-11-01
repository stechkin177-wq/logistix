"""Троттлинг POST /api/auth/login/ по нормализованному логину (не по IP): на демо-стенде все
запросы приходят с IP инфраструктуры, nginx limit_req отсутствует."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.core.api.auth import LoginThrottle
from apps.core.models import User

pytestmark = pytest.mark.django_db
URL = "/api/auth/login/"


@pytest.fixture(autouse=True)
def _small_rate(monkeypatch):
    cache.clear()
    monkeypatch.setattr(LoginThrottle, "THROTTLE_RATES", {"login": "3/min"})
    yield
    cache.clear()


def attempt(login, password="wrong-pass-1", **extra):
    return APIClient().post(URL, {"login": login, "password": password}, format="json", **extra)


def test_fourth_attempt_is_429_with_project_format():
    for _ in range(3):
        assert attempt("a@x.kz").status_code == 401
    r = attempt("a@x.kz")
    assert r.status_code == 429
    assert r.data["code"] == "throttled" and r.data["detail"]


def test_other_login_unaffected():
    for _ in range(4):
        attempt("a@x.kz")
    assert attempt("b@x.kz").status_code == 401


def test_key_is_normalised_email():
    for v in ("a@x.kz", "A@X.KZ", " a@x.kz ", "a@X.kz"):
        attempt(v)
    assert attempt("a@x.kz").status_code == 429


def test_key_is_normalised_phone():
    for v in ("+7 701 111 22 33", "8 (701) 111-22-33", "+77011112233"):
        attempt(v)
    assert attempt("87011112233").status_code == 429


def test_successful_attempts_count_too():
    User.objects.create_user(email="ok@x.kz", password="Good-pass-12345")
    for _ in range(3):
        attempt("ok@x.kz", "Good-pass-12345")  # 403: нет компании, но попытка учтена
    assert attempt("ok@x.kz", "Good-pass-12345").status_code == 429


def test_not_keyed_by_ip():
    for i in range(3):
        attempt("a@x.kz", REMOTE_ADDR=f"10.0.0.{i}")
    assert attempt("a@x.kz", REMOTE_ADDR="10.9.9.9").status_code == 429
    assert attempt("c@x.kz", REMOTE_ADDR="10.0.0.0").status_code == 401


def test_invalid_phone_falls_back_to_raw_string_hash():
    for _ in range(3):
        assert attempt("12345").status_code == 400
    assert attempt("12345").status_code == 429


def test_cache_keys_contain_no_identifier_or_password():
    attempt("secret.person@x.kz", "Very-Secret-Pw-1")
    attempt("+7 701 555 44 33", "Very-Secret-Pw-2")
    keys = [k for k in cache._cache.keys() if "throttle_login" in k]
    assert len(keys) == 2
    for k in keys:
        for bad in ("secret", "person", "x.kz", "7015554433", "701", "Secret", "Pw"):
            assert bad not in k


def test_missing_login_is_400_not_500():
    r = APIClient().post(URL, {"password": "x"}, format="json")
    assert r.status_code == 400
