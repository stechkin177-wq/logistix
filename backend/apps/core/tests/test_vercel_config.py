"""Конфигурация демо-стенда на Vercel: requirements.txt и vercel.json."""

import json
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BACKEND = REPO / "backend"
WEB = REPO / "web"
# gunicorn нужен только VPS/Docker; на Vercel процесс-менеджер платформы.
NOT_ON_VERCEL = {"gunicorn"}


def _name(spec):
    return re.split(r"[<>=!~\[ ;]", spec, maxsplit=1)[0].lower().replace("_", "-")


def _lines(path):
    return [
        ln.strip()
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def test_requirements_in_sync_with_pyproject():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]
    expected = [d for d in project["dependencies"] if _name(d) not in NOT_ON_VERCEL]
    assert _lines(BACKEND / "requirements.txt") == expected


def test_requirements_has_no_dev_or_server_deps():
    names = {_name(x) for x in _lines(BACKEND / "requirements.txt")}
    assert not names & NOT_ON_VERCEL
    for dev in ("pytest", "pytest-django", "pytest-env", "factory-boy", "time-machine", "ruff"):
        assert dev not in names


def _load(path):
    return json.loads(path.read_text())


def _no_secrets(text):
    assert not re.search(r"://[^/\s\"]+:[^@/\s\"]+@", text), "учётные данные в URL"
    assert "postgres" not in text.lower()


def test_backend_vercel_json():
    path = BACKEND / "vercel.json"
    cfg = _load(path)
    assert cfg["regions"] == ["fra1"]
    fn = cfg["functions"]["config/wsgi.py"]
    assert isinstance(fn["maxDuration"], int) and 1 <= fn["maxDuration"] <= 60
    for pat in ("**/tests/**", "staticfiles/**", "**/__pycache__/**"):
        assert pat in fn["excludeFiles"]
    # миграции и collectstatic не запускаются при сборке
    assert "buildCommand" not in cfg
    assert "crons" not in cfg
    _no_secrets(path.read_text())


def test_backend_entrypoint_is_declared():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    assert project["tool"]["vercel"]["entrypoint"] == "config.wsgi:application"
    assert (
        'WSGI_APPLICATION = "config.wsgi.application"'
        in (BACKEND / "config" / "settings.py").read_text()
    )


def test_web_vercel_json_rewrites():
    path = WEB / "vercel.json"
    cfg = _load(path)
    assert cfg["framework"] == "vite"
    rewrites = cfg["rewrites"]
    # Именно регулярное выражение: `:path*` не срабатывает для адресов со слэшем в конце
    # (/api/auth/login/), а Django использует только такие адреса.
    assert rewrites[0]["source"] == "/api/(.*)"
    assert re.fullmatch(rewrites[0]["source"], "/api/auth/login/")
    assert rewrites[0]["destination"].startswith("https://")
    assert rewrites[0]["destination"].endswith("/api/$1")
    assert all(not r["source"].startswith("/media") for r in rewrites)
    last = rewrites[-1]
    assert last["destination"] == "/index.html"
    # SPA-фолбэк не перехватывает api, assets и файлы с расширением
    assert "assets" in last["source"] and "api" in last["source"]
    assert re.fullmatch(last["source"], "/orders/12")
    assert not re.fullmatch(last["source"], "/assets/index-abc.js")
    assert not re.fullmatch(last["source"], "/api/health/")
    assert not re.fullmatch(last["source"], "/favicon.svg")
    _no_secrets(path.read_text())


def test_web_vercel_json_security_headers():
    cfg = _load(WEB / "vercel.json")
    blocks = [h for h in cfg["headers"] if h["source"] == "/(.*)"]
    assert blocks
    headers = {h["key"].lower(): h["value"] for h in blocks[0]["headers"]}
    csp = headers["content-security-policy"]
    for directive in (
        "default-src 'self'",
        "img-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ):
        assert directive in csp
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"]
    assert "geolocation=()" in headers["permissions-policy"]
    assert "strict-transport-security" not in headers


def test_env_examples_have_only_placeholders():
    text = (BACKEND / ".env.vercel.example").read_text()
    assert "DJANGO_SERVERLESS=true" in text
    assert (
        "DATABASE_URL=" in text and "-pooler" not in text.split("DATABASE_URL=")[1].split("\n")[0]
    )
    _no_secrets(text.replace("postgresql://", "").replace("CHANGE-ME", ""))
