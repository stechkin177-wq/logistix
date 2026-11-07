"""Воспроизводимая проверка обновления с состояния ДО подзадачи 1.4.1 (временные БД)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_upgrade_task_1_4_1.py"


@pytest.mark.django_db
def test_upgrade_rollback_reapply_and_rates_preflight():
    """Скрипт сам создаёт и удаляет отдельные БД; основная тестовая БД не затрагивается."""
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
    assert all(f"OK {n}:" in done.stdout for n in (1, 2, 3)), done.stdout
