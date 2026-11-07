"""RLS новых таблиц под реальной ролью logistix_app после каждой миграции M1..M6 (временная БД)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_rls_task_1_4_1.py"


@pytest.mark.django_db
def test_rls_under_app_role_after_every_migration():
    """Скрипт сам создаёт и удаляет БД, применяет deploy/db-init.sql и проверяет каждый шаг."""
    from django.conf import settings

    db = settings.DATABASES["default"]
    url = (
        f"postgres://{db['USER']}:{db['PASSWORD']}@{db['HOST'] or '127.0.0.1'}:"
        f"{db['PORT'] or 5432}/postgres"
    )
    done = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**os.environ, "DATABASE_URL": url, "DJANGO_DEBUG": "true"},
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    for step in ("base", "M1", "M2", "M3", "M4", "M5", "M6"):
        assert f"OK {step} " in done.stdout, done.stdout
    assert "tables_missing_rls() == []" in done.stdout
