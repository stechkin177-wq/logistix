"""Общие помощники проверочных скриптов подзадачи 1.4.1 (временная БД, manage.py, роль)."""

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
DEFAULT_URL = "postgres://logistix:logistix@127.0.0.1:5432/logistix"
APP_ROLE = "logistix_app"
APP_PASSWORD = "logistix_app"  # пароль РАЗРАБОТКИ, как в deploy/db-init.sql


def with_db(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def with_user(url: str, user: str, password: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    netloc = f"{user}:{password}@{host}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))


def manage(url: str, *args: str, stdin: str | None = None, env_extra: dict | None = None) -> str:
    env = {**os.environ, "DJANGO_DEBUG": "true", "DATABASE_URL": url, **(env_extra or {})}
    done = subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=BACKEND,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError(f"manage.py {' '.join(args)} failed:\n{done.stdout}\n{done.stderr}")
    return done.stdout


def manage_result(url: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Как manage(), но без исключения: нужен код возврата и вывод (ожидаемая ошибка миграции)."""
    env = {**os.environ, "DJANGO_DEBUG": "true", "DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=BACKEND,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
    )


class TempDatabase:
    """Временная БД; удаляется при выходе (в том числе по ошибке)."""

    def __init__(self, base_url: str, prefix: str):
        self.base_url = base_url
        self.name = f"{prefix}_{uuid.uuid4().hex[:8]}"
        self.url = with_db(base_url, self.name)
        self.admin = None

    def __enter__(self):
        self.admin = psycopg.connect(with_db(self.base_url, "postgres"), autocommit=True)
        self.admin.execute(f'CREATE DATABASE "{self.name}"')
        return self

    def __exit__(self, *exc):
        try:
            self.admin.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')
        finally:
            self.admin.close()
        return False


def apply_db_init(db_url: str) -> None:
    """Применяет deploy/db-init.sql (роль logistix_app и права, как в продакшене) к БД."""
    env = {
        **os.environ,
        "APP_DB_PASSWORD": APP_PASSWORD,
        "PGOPTIONS": "-c client_min_messages=warning",
    }
    done = subprocess.run(
        [
            "psql",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            db_url,
            "-f",
            str(REPO / "deploy" / "db-init.sql"),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError(f"db-init.sql failed:\n{done.stdout}\n{done.stderr}")
