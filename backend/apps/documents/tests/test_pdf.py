"""Конвертация DOCX в PDF: subprocess подменяется; реальный запуск - только при наличии soffice."""

import fcntl
import io
import subprocess
import tempfile
from pathlib import Path

import pytest
from docx import Document

from apps.documents import pdf
from apps.documents.errors import DocumentError


def _docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Тестовый документ " * 50)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _tmp_dirs() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("logistix-pdf-*")}


@pytest.fixture
def fake_soffice(monkeypatch):
    monkeypatch.setattr(pdf.shutil, "which", lambda name: "/usr/bin/soffice")


def test_pdf_available_reflects_binary(monkeypatch):
    monkeypatch.setattr(pdf.shutil, "which", lambda name: "/usr/bin/soffice")
    assert pdf.pdf_available() is True
    monkeypatch.setattr(pdf.shutil, "which", lambda name: None)
    assert pdf.pdf_available() is False


@pytest.mark.skipif(not pdf.pdf_available(), reason="LibreOffice не установлен")
def test_convert_produces_pdf():
    before = _tmp_dirs()
    out = pdf.convert_to_pdf(_docx())
    assert out.startswith(b"%PDF")
    assert len(out) > 1024
    assert _tmp_dirs() == before


def test_missing_binary_raises_pdf_unavailable(monkeypatch):
    monkeypatch.setattr(pdf.shutil, "which", lambda name: None)
    with pytest.raises(DocumentError) as exc:
        pdf.convert_to_pdf(_docx())
    assert exc.value.detail.code == "pdf_unavailable"
    assert exc.value.status_code == 503


def test_timeout_raises_pdf_unavailable(monkeypatch, fake_soffice):
    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(pdf.subprocess, "run", boom)
    with pytest.raises(DocumentError) as exc:
        pdf.convert_to_pdf(_docx())
    assert exc.value.detail.code == "pdf_unavailable"
    assert exc.value.status_code == 503


def test_nonzero_exit_and_missing_output_raise(monkeypatch, fake_soffice):
    monkeypatch.setattr(
        pdf.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"err")
    )
    with pytest.raises(DocumentError) as exc:
        pdf.convert_to_pdf(_docx())
    assert exc.value.detail.code == "pdf_unavailable"
    # код 0, но файла нет
    monkeypatch.setattr(
        pdf.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, b"", b"")
    )
    with pytest.raises(DocumentError):
        pdf.convert_to_pdf(_docx())


def test_command_is_isolated_and_bounded(monkeypatch, fake_soffice):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        (outdir / "document.pdf").write_bytes(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(pdf.subprocess, "run", fake_run)
    assert pdf.convert_to_pdf(_docx()) == b"%PDF-1.4 fake"
    cmd = seen["cmd"]
    assert "--headless" in cmd and "--norestore" in cmd
    assert any(a.startswith("-env:UserInstallation=file://") for a in cmd)
    assert seen["kwargs"]["timeout"] == 60
    assert seen["kwargs"]["check"] is False


def test_temp_dir_cleaned_after_success_and_failure(monkeypatch, fake_soffice):
    before = _tmp_dirs()

    def ok(cmd, **kwargs):
        (Path(cmd[cmd.index("--outdir") + 1]) / "document.pdf").write_bytes(b"%PDF-x")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(pdf.subprocess, "run", ok)
    pdf.convert_to_pdf(_docx())
    assert _tmp_dirs() == before

    monkeypatch.setattr(
        pdf.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"")
    )
    with pytest.raises(DocumentError):
        pdf.convert_to_pdf(_docx())
    assert _tmp_dirs() == before


def test_busy_lock_times_out(monkeypatch, settings, fake_soffice):
    settings.PDF_LOCK_WAIT_SECONDS = 0.2
    called = []
    monkeypatch.setattr(pdf.subprocess, "run", lambda *a, **k: called.append(1))
    with open(pdf._LOCK_PATH, "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        try:
            with pytest.raises(DocumentError) as exc:
                pdf.convert_to_pdf(_docx())
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
    assert exc.value.detail.code == "pdf_unavailable"
    assert exc.value.status_code == 503
    assert called == []
