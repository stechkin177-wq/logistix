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


class FakePopen:
    """Подмена Popen: pdf_bytes - что «записал» soffice (None - ничего)."""

    instances: list = []
    returncode_value = 0
    pdf_bytes: bytes | None = None
    timeout = False

    def __init__(self, cmd, **kwargs):
        self.cmd, self.kwargs, self.pid, self.waited = cmd, kwargs, 4242, False
        self.returncode = type(self).returncode_value
        type(self).instances.append(self)

    def communicate(self, timeout=None):
        if type(self).timeout:
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        if type(self).pdf_bytes is not None:
            outdir = Path(self.cmd[self.cmd.index("--outdir") + 1])
            (outdir / "document.pdf").write_bytes(type(self).pdf_bytes)
        return b"", b""

    def wait(self):
        self.waited = True


@pytest.fixture
def popen(monkeypatch):
    cls = type(
        "P",
        (FakePopen,),
        {"instances": [], "returncode_value": 0, "pdf_bytes": None, "timeout": False},
    )
    killed = []
    monkeypatch.setattr(pdf.subprocess, "Popen", cls)
    monkeypatch.setattr(pdf.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
    cls.killed = killed
    return cls


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


def test_timeout_kills_process_group(popen, fake_soffice):
    popen.timeout = True
    with pytest.raises(DocumentError) as exc:
        pdf.convert_to_pdf(_docx())
    assert exc.value.detail.code == "pdf_unavailable"
    assert exc.value.status_code == 503
    assert popen.killed == [(4242, pdf.signal.SIGKILL)]
    assert popen.instances[0].waited
    assert popen.instances[0].kwargs["start_new_session"] is True


def test_popen_oserror_raises_pdf_unavailable(monkeypatch, fake_soffice):
    def boom(*a, **k):
        raise OSError("no exec")

    monkeypatch.setattr(pdf.subprocess, "Popen", boom)
    with pytest.raises(DocumentError) as exc:
        pdf.convert_to_pdf(_docx())
    assert exc.value.status_code == 503


def test_lock_file_oserror_raises_pdf_unavailable(monkeypatch, fake_soffice):
    def boom(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(pdf.os, "open", boom)
    with pytest.raises(DocumentError) as exc:
        pdf.convert_to_pdf(_docx())
    assert exc.value.status_code == 503


def test_nonzero_exit_and_missing_output_raise(popen, fake_soffice):
    popen.returncode_value = 1
    with pytest.raises(DocumentError) as exc:
        pdf.convert_to_pdf(_docx())
    assert exc.value.detail.code == "pdf_unavailable"
    popen.returncode_value = 0  # код 0, но файла нет
    with pytest.raises(DocumentError):
        pdf.convert_to_pdf(_docx())


def test_command_is_isolated_and_bounded(popen, fake_soffice):
    popen.pdf_bytes = b"%PDF-1.4 fake"
    assert pdf.convert_to_pdf(_docx()) == b"%PDF-1.4 fake"
    inst = popen.instances[0]
    assert "--headless" in inst.cmd and "--norestore" in inst.cmd
    assert any(a.startswith("-env:UserInstallation=file://") for a in inst.cmd)
    env = inst.kwargs["env"]
    assert set(env) == {"PATH", "HOME"}
    assert env["HOME"].startswith(tempfile.gettempdir())
    assert popen.killed  # группа добивается и после успеха


def test_temp_dir_cleaned_after_success_and_failure(popen, fake_soffice):
    before = _tmp_dirs()
    popen.pdf_bytes = b"%PDF-x"
    pdf.convert_to_pdf(_docx())
    assert _tmp_dirs() == before
    popen.returncode_value = 1
    with pytest.raises(DocumentError):
        pdf.convert_to_pdf(_docx())
    assert _tmp_dirs() == before


def test_busy_lock_times_out(popen, settings, fake_soffice):
    settings.PDF_LOCK_WAIT_SECONDS = 0.2
    with open(pdf._LOCK_PATH, "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        try:
            with pytest.raises(DocumentError) as exc:
                pdf.convert_to_pdf(_docx())
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
    assert exc.value.detail.code == "pdf_unavailable"
    assert exc.value.status_code == 503
    assert popen.instances == []
