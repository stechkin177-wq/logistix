"""RLS для finance.0008 и finance.0009 под реальной ролью logistix_app (пошагово, 1.4.13)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_rls_task_1_4_13.py"


@pytest.mark.django_db
def test_rls_step_by_step_for_migrations_0008_0009():
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
    assert "OK: 1.4.13 RLS" in done.stdout
    assert "OK мутация" in done.stdout
    assert "OK preflight 0008" in done.stdout
