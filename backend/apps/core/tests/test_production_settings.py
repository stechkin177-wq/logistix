"""Продакшен-настройки и Sentry: env-управляемые, безопасные значения по умолчанию."""

import importlib.util
from pathlib import Path
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError

from config import observability

SETTINGS_PATH = Path(__file__).resolve().parents[3] / "config" / "settings.py"
EXAMPLE_ENV = Path(__file__).resolve().parents[4] / "deploy" / ".env.prod.example"

BASE_ENV = {
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": "k" * 60,
}


def load_settings(monkeypatch, **env):
    for name in list(__import__("os").environ):
        if name.startswith(("DJANGO_", "SENTRY_")):
            monkeypatch.delenv(name)
    for k, v in {**BASE_ENV, **env}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("settings_prod_under_test", SETTINGS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prod_defaults_are_conservative(monkeypatch):
    s = load_settings(monkeypatch)
    assert s.ALLOWED_HOSTS == []
    assert not hasattr(s, "SECURE_PROXY_SSL_HEADER")
    assert s.SESSION_COOKIE_SECURE is False and s.CSRF_COOKIE_SECURE is False
    assert s.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert s.X_FRAME_OPTIONS == "DENY"
    assert s.SECURE_REFERRER_POLICY
    assert s.SECURE_HSTS_SECONDS == 0
    assert s.ADMIN_ENABLED is True
    assert s.CSRF_TRUSTED_ORIGINS == []


def test_prod_behind_tls_proxy(monkeypatch):
    s = load_settings(
        monkeypatch,
        DJANGO_BEHIND_TLS_PROXY="true",
        DJANGO_ALLOWED_HOSTS="a.kz, b.kz",
        DJANGO_CSRF_TRUSTED_ORIGINS="https://a.kz",
        DJANGO_HSTS_SECONDS="3600",
        DJANGO_ADMIN_ENABLED="false",
    )
    assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE and s.SECURE_SSL_REDIRECT
    assert s.ALLOWED_HOSTS == ["a.kz", "b.kz"]
    assert s.CSRF_TRUSTED_ORIGINS == ["https://a.kz"]
    assert s.SECURE_HSTS_SECONDS == 3600
    assert s.ADMIN_ENABLED is False


def test_debug_does_not_enable_prod_flags(monkeypatch):
    s = load_settings(monkeypatch, DJANGO_DEBUG="true", DJANGO_BEHIND_TLS_PROXY="true")
    assert not hasattr(s, "SECURE_PROXY_SSL_HEADER")
    assert "localhost" in s.ALLOWED_HOSTS


def _example_env():
    env = {}
    for line in EXAMPLE_ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def test_check_deploy_clean_with_example_prod_env(monkeypatch, settings):
    """manage.py check --deploy без предупреждений с настройками из deploy/.env.prod.example."""
    s = load_settings(monkeypatch, **_example_env())
    for name in (
        "DEBUG",
        "ALLOWED_HOSTS",
        "SECRET_KEY",
        "SECURE_PROXY_SSL_HEADER",
        "SECURE_SSL_REDIRECT",
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
        "SECURE_CONTENT_TYPE_NOSNIFF",
        "SECURE_REFERRER_POLICY",
        "X_FRAME_OPTIONS",
        "SECURE_HSTS_SECONDS",
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "SECURE_HSTS_PRELOAD",
        "SILENCED_SYSTEM_CHECKS",
    ):
        setattr(settings, name, getattr(s, name))
    try:
        call_command("check", "--deploy", "--fail-level", "WARNING")
    except SystemCheckError as exc:  # pragma: no cover
        pytest.fail(str(exc))


def test_sentry_not_initialised_without_dsn():
    with mock.patch("sentry_sdk.init") as init:
        assert observability.init_sentry(dsn="") is False
    init.assert_not_called()


def test_sentry_init_kwargs_exact(monkeypatch):
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.25")
    with mock.patch("sentry_sdk.init") as init:
        assert observability.init_sentry(dsn="https://k@sentry.example.kz/1") is True
    init.assert_called_once_with(
        dsn="https://k@sentry.example.kz/1",
        environment="staging",
        traces_sample_rate=0.25,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=observability.scrub_event,
    )


def test_sentry_defaults(monkeypatch):
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
    with mock.patch("sentry_sdk.init") as init:
        observability.init_sentry(dsn="https://k@s.kz/1")
    kwargs = init.call_args.kwargs
    assert kwargs["traces_sample_rate"] == 0.0 and kwargs["environment"] == "production"


def test_scrub_event_drops_bodies_cookies_auth():
    event = {
        "request": {
            "data": {"password": "x"},
            "cookies": {"sessionid": "y"},
            "query_string": "token=1",
            "headers": {"Authorization": "Bearer t", "Cookie": "a=b", "Accept": "*/*"},
        },
        "user": {"email": "a@b.kz"},
    }
    out = observability.scrub_event(event)
    assert out["request"] == {"headers": {"Accept": "*/*"}}
    assert "user" not in out
