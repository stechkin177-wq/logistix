"""Конвертация DOCX в PDF через LibreOffice (headless).

Каждая конвертация идёт отдельным процессом с изолированным профилем во временном
каталоге; одновременно выполняется одна (межпроцессная блокировка `flock`), чтобы
не исчерпать память. Ничего не остаётся на диске. Любой сбой - `pdf_unavailable` (503).
"""

import contextlib
import fcntl
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from django.conf import settings

from .errors import DocumentError

PDF_TIMEOUT_SECONDS = 60
PDF_LOCK_WAIT_SECONDS = 30
_LOCK_PATH = Path(tempfile.gettempdir()) / "logistix-soffice.lock"


def _unavailable(detail: str = "Формирование PDF сейчас недоступно.") -> DocumentError:
    return DocumentError("pdf_unavailable", detail, status_code=503)


def pdf_available() -> bool:
    return shutil.which("soffice") is not None


@contextlib.contextmanager
def _exclusive_lock(wait_seconds: float):
    fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise _unavailable("Конвертация PDF занята, повторите позже.") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _run_soffice(cmd: list[str], env: dict[str, str], timeout: float) -> int:
    """Запуск в отдельной группе процессов; по завершении/сбое убивается вся группа
    (soffice - обёртка sh -> oosplash -> soffice.bin, внуки не должны пережить вызов)."""
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        proc.communicate(timeout=timeout)
        return proc.returncode
    finally:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            proc.wait()


def convert_to_pdf(docx: bytes) -> bytes:
    binary = shutil.which("soffice")
    if binary is None:
        raise _unavailable()
    timeout = getattr(settings, "PDF_TIMEOUT_SECONDS", PDF_TIMEOUT_SECONDS)
    wait = getattr(settings, "PDF_LOCK_WAIT_SECONDS", PDF_LOCK_WAIT_SECONDS)
    try:
        with _exclusive_lock(wait), tempfile.TemporaryDirectory(prefix="logistix-pdf-") as tmp:
            tmp_dir = Path(tmp)
            home = tmp_dir / "home"
            home.mkdir()
            source = tmp_dir / "document.docx"
            source.write_bytes(docx)
            cmd = [
                binary,
                "--headless",
                "--norestore",
                f"-env:UserInstallation=file://{tmp_dir / 'profile'}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_dir),
                str(source),
            ]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
            returncode = _run_soffice(cmd, env, timeout)
            output = tmp_dir / "document.pdf"
            if returncode != 0 or not output.is_file():
                raise _unavailable()
            return output.read_bytes()
    except (subprocess.TimeoutExpired, OSError):
        raise _unavailable() from None
