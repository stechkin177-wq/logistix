"""DJANGO_SERVERLESS и связанные с ним настройки (демо на Vercel). Значения по умолчанию
для разработки/VPS/тестов не меняются."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from .test_production_settings import load_settings

DIRECT = "postgresql://u:p@ep-cool.c-2.eu-central-1.aws.neon.tech/db?sslmode=require"
POOLED = "postgresql://u:p@ep-cool-pooler.c-2.eu-central-1.aws.neon.tech/db?sslmode=require"


def test_defaults_unchanged(monkeypatch):
    s = load_settings(monkeypatch)
    assert s.SERVERLESS is False
    assert s.DATABASES["default"]["CONN_MAX_AGE"] == 60
    assert "sslmode" not in s.DATABASES["default"].get("OPTIONS", {})
    assert s.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] == "10/minute"


def test_conn_max_age_env(monkeypatch):
    s = load_settings(monkeypatch, DATABASE_CONN_MAX_AGE="5")
    assert s.DATABASES["default"]["CONN_MAX_AGE"] == 5


def test_serverless_forces_conn_max_age_zero(monkeypatch):
    s = load_settings(monkeypatch, DJANGO_SERVERLESS="true", DATABASE_URL=DIRECT)
    assert s.SERVERLESS is True
    assert s.DATABASES["default"]["CONN_MAX_AGE"] == 0


def test_serverless_explicit_conn_max_age_wins(monkeypatch):
    s = load_settings(
        monkeypatch, DJANGO_SERVERLESS="true", DATABASE_URL=DIRECT, DATABASE_CONN_MAX_AGE="30"
    )
    assert s.DATABASES["default"]["CONN_MAX_AGE"] == 30


def test_ssl_require_switch(monkeypatch):
    s = load_settings(
        monkeypatch, DATABASE_SSL_REQUIRE="true", DATABASE_URL="postgres://u:p@h:5432/d"
    )
    assert s.DATABASES["default"]["OPTIONS"]["sslmode"] == "require"


def test_ssl_require_keeps_stricter_url_mode(monkeypatch):
    s = load_settings(
        monkeypatch,
        DATABASE_SSL_REQUIRE="true",
        DATABASE_URL="postgres://u:p@h:5432/d?sslmode=verify-full",
    )
    assert s.DATABASES["default"]["OPTIONS"]["sslmode"] == "verify-full"


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer"])
def test_ssl_require_upgrades_weak_url_modes(monkeypatch, mode):
    s = load_settings(
        monkeypatch,
        DATABASE_SSL_REQUIRE="true",
        DATABASE_URL=f"postgres://u:p@h:5432/d?sslmode={mode}",
    )
    assert s.DATABASES["default"]["OPTIONS"]["sslmode"] == "require"


def test_ssl_weak_mode_untouched_without_switch(monkeypatch):
    s = load_settings(monkeypatch, DATABASE_URL="postgres://u:p@h:5432/d?sslmode=prefer")
    assert s.DATABASES["default"]["OPTIONS"]["sslmode"] == "prefer"


def test_ssl_via_url(monkeypatch):
    s = load_settings(monkeypatch, DATABASE_URL=DIRECT)
    assert s.DATABASES["default"]["OPTIONS"]["sslmode"] == "require"


def test_serverless_rejects_pooled_url(monkeypatch):
    with pytest.raises(ImproperlyConfigured, match="пулер"):
        load_settings(monkeypatch, DJANGO_SERVERLESS="true", DATABASE_URL=POOLED)


def test_serverless_rejects_pooled_url_even_in_debug(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        load_settings(
            monkeypatch,
            DJANGO_SERVERLESS="true",
            DJANGO_DEBUG="true",
            DATABASE_URL=POOLED,
            DATABASE_POOLER_OK="true",
        )


def test_production_rejects_pooled_url_without_ack(monkeypatch):
    with pytest.raises(ImproperlyConfigured, match="DATABASE_POOLER_OK"):
        load_settings(monkeypatch, DATABASE_URL=POOLED)


def test_production_pooled_url_with_ack(monkeypatch):
    s = load_settings(monkeypatch, DATABASE_URL=POOLED, DATABASE_POOLER_OK="true")
    assert s.SERVERLESS is False


def test_debug_pooled_url_not_checked(monkeypatch):
    load_settings(monkeypatch, DJANGO_DEBUG="true", DATABASE_URL=POOLED)


def test_production_renderer_is_json_only(monkeypatch):
    s = load_settings(monkeypatch)
    assert s.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] == ["rest_framework.renderers.JSONRenderer"]


def test_serverless_renderer_is_json_only_even_in_debug(monkeypatch):
    s = load_settings(
        monkeypatch, DJANGO_SERVERLESS="true", DJANGO_DEBUG="true", DATABASE_URL=DIRECT
    )
    assert s.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] == ["rest_framework.renderers.JSONRenderer"]


def test_debug_keeps_drf_default_renderers(monkeypatch):
    s = load_settings(monkeypatch, DJANGO_DEBUG="true")
    assert "DEFAULT_RENDERER_CLASSES" not in s.REST_FRAMEWORK


def test_login_throttle_rate_env(monkeypatch):
    s = load_settings(monkeypatch, THROTTLE_LOGIN="3/minute")
    assert s.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] == "3/minute"


def test_demo_has_no_wildcard_hosts(monkeypatch):
    s = load_settings(monkeypatch, DJANGO_SERVERLESS="true", DATABASE_URL=DIRECT)
    assert "*" not in s.ALLOWED_HOSTS and s.ALLOWED_HOSTS == []


def test_ssl_redirect_flag_defaults_to_behind_proxy(monkeypatch):
    s = load_settings(monkeypatch, DJANGO_BEHIND_TLS_PROXY="true")
    assert s.SSL_REDIRECT is True and s.SECURE_SSL_REDIRECT is True
    s = load_settings(monkeypatch)
    assert s.SSL_REDIRECT is False and not hasattr(s, "SECURE_SSL_REDIRECT")


def test_ssl_redirect_false_keeps_other_tls_proxy_settings(monkeypatch):
    s = load_settings(monkeypatch, DJANGO_BEHIND_TLS_PROXY="true", DJANGO_SSL_REDIRECT="false")
    assert s.SSL_REDIRECT is False
    assert not getattr(s, "SECURE_SSL_REDIRECT", False)
    assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE


def test_ssl_redirect_true_without_proxy_is_not_enabled(monkeypatch):
    # редирект без доверенного X-Forwarded-Proto дал бы бесконечный цикл
    s = load_settings(monkeypatch, DJANGO_SSL_REDIRECT="true")
    assert not getattr(s, "SECURE_SSL_REDIRECT", False)
