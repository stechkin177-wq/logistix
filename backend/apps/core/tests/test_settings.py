import importlib.util
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

SETTINGS_PATH = Path(__file__).resolve().parents[3] / "config" / "settings.py"


def load_settings():
    spec = importlib.util.spec_from_file_location("settings_under_test", SETTINGS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secret_key_required_when_debug_false(monkeypatch):
    monkeypatch.setenv("DJANGO_DEBUG", "false")
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    with pytest.raises(ImproperlyConfigured):
        load_settings()


def test_debug_false_with_key_ok(monkeypatch):
    monkeypatch.setenv("DJANGO_DEBUG", "false")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 50)
    module = load_settings()
    assert module.DEBUG is False
    assert module.SECRET_KEY == "x" * 50


def test_debug_defaults_to_false(monkeypatch):
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    monkeypatch.setenv("DJANGO_SECRET_KEY", "k")
    assert load_settings().DEBUG is False
