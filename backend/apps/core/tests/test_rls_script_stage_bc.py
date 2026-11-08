"""Этапы 1.5-B и 1.5-C: RLS под реальной ролью logistix_app и миграции на данных (пошагово)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_rls_stage_BC.py"


@pytest.mark.django_db
def test_rls_and_data_migrations_step_by_step_for_stages_b_and_c():
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
        timeout=1800,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "OK: этапы 1.5-B и 1.5-C" in done.stdout
    assert "OK мутация" in done.stdout
    assert "OK C1-0012" in done.stdout
    assert "OK защита отката" in done.stdout
