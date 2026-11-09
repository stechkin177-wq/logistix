#!/usr/bin/env python3
"""Локальный запуск LogistiX с тестовой БД (вымышленные данные). Только стандартная библиотека.

    python local/run.py start      # подготовить всё и запустить (backend :8000, frontend :5173)
    python local/run.py totp       # текущий код TOTP владельца (локально, без телефона)
    python local/run.py reset      # удалить тестовую БД и создать заново
    python local/run.py stop       # остановить PostgreSQL в Docker

Что нужно: Python 3.12+, Node.js 20+, Docker (PostgreSQL 16 в контейнере) ЛИБО свой локальный
PostgreSQL 16 (ключ --no-docker: роль logistix/logistix, утилита psql в PATH). Ничего не публикуется,
внешних БД и сервисов нет; используется только 127.0.0.1.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
WEB = ROOT / "web"
VENV = ROOT / ".venv-local"
DB_NAME = "logistix_demo"
OWNER_URL = f"postgres://logistix:logistix@127.0.0.1:5432/{DB_NAME}"
APP_URL = f"postgres://logistix_app:logistix_app@127.0.0.1:5432/{DB_NAME}"
SECRET = "local-demo-only-not-a-secret-0123456789-abcdefghijklmnopqrstuv"
IS_WIN = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def say(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def run(cmd, **kw):
    kw.setdefault("check", True)
    return subprocess.run([str(c) for c in cmd], **kw)


def need(tool: str, hint: str) -> None:
    if shutil.which(tool) is None:
        sys.exit(f"Не найден «{tool}». {hint}")


class Pg:
    """Доступ к PostgreSQL: контейнер Docker либо локальный psql."""

    def __init__(self, docker: bool):
        self.docker = docker

    def psql(self, args, stdin_text=None, db="postgres"):
        base = (
            ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "exec", "-T", "postgres", "psql"]
            if self.docker
            else ["psql", "-h", "127.0.0.1"]
        )
        cmd = base + ["-U", "logistix", "-d", db, "-v", "ON_ERROR_STOP=1", "-q", *args]
        env = dict(os.environ, PGPASSWORD="logistix")
        return run(cmd, input=stdin_text, text=True, env=env, cwd=ROOT, capture_output=True)

    def up(self):
        if self.docker:
            say("PostgreSQL 16 в Docker (docker compose up -d postgres)")
            run(["docker", "compose", "-f", ROOT / "docker-compose.yml", "up", "-d", "postgres"], cwd=ROOT)
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                self.psql(["-c", "select 1"])
                return
            except (subprocess.CalledProcessError, FileNotFoundError):
                time.sleep(2)
        sys.exit("PostgreSQL не отвечает на 127.0.0.1:5432 (логин logistix / пароль logistix)")

    def exists(self) -> bool:
        out = self.psql(["-tAc", f"select 1 from pg_database where datname='{DB_NAME}'"]).stdout
        return out.strip() == "1"

    def create(self):
        say(f"Создаю базу {DB_NAME} и роль приложения logistix_app (без обхода RLS)")
        self.psql(["-c", f"CREATE DATABASE {DB_NAME} OWNER logistix"])
        sql = (ROOT / "deploy" / "db-init.sql").read_text(encoding="utf-8")
        self.psql([], stdin_text=sql, db=DB_NAME)

    def drop(self):
        say(f"Удаляю базу {DB_NAME}")
        self.psql(["-c", f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"])


def backend_env(url: str) -> dict:
    return dict(os.environ, DJANGO_DEBUG="true", DJANGO_SECRET_KEY=SECRET, DATABASE_URL=url)


def manage(*args, url=APP_URL, **kw):
    return run([VENV_PY, "manage.py", *args], cwd=BACKEND, env=backend_env(url), **kw)


def ensure_venv():
    if not VENV_PY.exists():
        say("Создаю виртуальное окружение Python (.venv-local) и ставлю зависимости (один раз)")
        run([sys.executable, "-m", "venv", VENV])
        run([VENV_PY, "-m", "pip", "install", "-q", "--upgrade", "pip"])
        run([VENV_PY, "-m", "pip", "install", "-q", "-r", BACKEND / "requirements.txt"])


def ensure_web():
    if not (WEB / "node_modules").exists():
        say("Ставлю зависимости фронтенда (npm ci, один раз)")
        run(["npm", "ci"], cwd=WEB, shell=IS_WIN)


def prepare(pg: Pg, fresh: bool):
    pg.up()
    if fresh and pg.exists():
        pg.drop()
    created = False
    if not pg.exists():
        pg.create()
        created = True
    ensure_venv()
    say("Миграции (под ролью-владельцем базы)")
    manage("migrate", "-v", "0", url=OWNER_URL)
    if created:
        say("Тестовые данные (вымышленные)")
        manage("seed_demo")
    else:
        say("База уже существует: тестовые данные не пересоздаются (python local/run.py reset - начать заново)")


def start(pg: Pg):
    need("npm", "Нужен Node.js 20+ (npm).")
    if sys.version_info < (3, 12):
        sys.exit("Нужен Python 3.12 или новее.")
    prepare(pg, fresh=False)
    ensure_web()
    say("Запускаю backend (127.0.0.1:8000) и frontend (127.0.0.1:5173)")
    back = subprocess.Popen(
        [str(VENV_PY), "manage.py", "runserver", "127.0.0.1:8000", "--noreload"],
        cwd=BACKEND, env=backend_env(APP_URL),
    )  # fmt: skip
    front = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"], cwd=WEB, shell=IS_WIN
    )
    print(
        "\n  Откройте http://127.0.0.1:5173\n"
        "  Вход: owner@demo.local / Demo-pass-2026!  (затем код TOTP: python local/run.py totp)\n"
        "  Остановить: Ctrl+C\n",
        flush=True,
    )
    try:
        while back.poll() is None and front.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (back, front):
            if proc.poll() is None:
                proc.terminate()
        for proc in (back, front):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("command", choices=["start", "totp", "reset", "stop"])
    parser.add_argument("--no-docker", action="store_true", help="использовать свой локальный PostgreSQL 16")
    args = parser.parse_args()
    if not args.no_docker:
        need("docker", "Установите Docker Desktop либо запустите с ключом --no-docker (свой PostgreSQL 16).")
    else:
        need("psql", "Нужен клиент PostgreSQL (psql) в PATH.")
    pg = Pg(docker=not args.no_docker)
    if args.command == "start":
        start(pg)
    elif args.command == "reset":
        prepare(pg, fresh=True)
        say("Готово. Запуск: python local/run.py start")
    elif args.command == "totp":
        ensure_venv()
        manage("demo_totp")
    elif args.command == "stop":
        if pg.docker:
            run(["docker", "compose", "-f", ROOT / "docker-compose.yml", "stop", "postgres"], cwd=ROOT)
        else:
            print("С ключом --no-docker остановка PostgreSQL выполняется вручную.")


if __name__ == "__main__":
    main()
