"""RLS переключение/откат/заморозка (1.4.11) под реальной ролью logistix_app."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_rls_task_1_4_11.py"


@pytest.mark.django_db
def test_switch_rollback_freeze_under_app_role():
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
    assert "OK: 1.4.11" in done.stdout
