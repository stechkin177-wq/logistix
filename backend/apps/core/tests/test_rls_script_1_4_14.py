"""RLS для finance.0010 (снимки курса, FxRevaluation) под реальной ролью logistix_app (1.4.14)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_rls_task_1_4_14.py"


@pytest.mark.django_db
def test_rls_step_by_step_for_migration_0010():
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
    assert "OK: 1.4.14 RLS" in done.stdout
    assert "OK мутация" in done.stdout
    assert "OK откат 0010 -> 0009" in done.stdout
