"""Этапы 1.5-D и 1.5-E: RLS под реальной ролью logistix_app и миграции на данных (пошагово)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_rls_stage_DE.py"


@pytest.mark.django_db
def test_rls_and_data_migrations_step_by_step_for_stages_d_and_e():
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
    assert "OK: этапы 1.5-D и 1.5-E" in done.stdout
    assert "OK мутация" in done.stdout
    assert "OK D1-0014" in done.stdout
    assert "OK D3-core0019" in done.stdout
    assert "OK E2-finance0011" in done.stdout
    assert "OK откат-0013" in done.stdout
