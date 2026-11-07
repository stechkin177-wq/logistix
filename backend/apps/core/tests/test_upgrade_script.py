"""Воспроизводимая проверка обновления с состояния ДО задачи 1.1 (временная БД, откат, повтор)."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_upgrade_task_1_1.py"


@pytest.mark.django_db
def test_upgrade_rollback_and_reapply_on_existing_data():
    """Скрипт сам создаёт и удаляет отдельную БД; основная тестовая БД не затрагивается."""
    from django.conf import settings

    db = settings.DATABASES["default"]
    url = (
        f"postgres://{db['USER']}:{db['PASSWORD']}@{db['HOST'] or '127.0.0.1'}:"
        f"{db['PORT'] or 5432}/postgres"
    )
    import os

    done = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**os.environ, "DATABASE_URL": url, "DJANGO_DEBUG": "true"},
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "OK:" in done.stdout
