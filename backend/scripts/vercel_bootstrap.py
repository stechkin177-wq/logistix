"""Одноразовая начальная настройка демо-БД (Supabase) из сборки Vercel.

Зачем: из среды разработчика и CI нет сети до базы, а у сборки Vercel она есть. Скрипт
запускают в ВРЕМЕННОМ проекте Vercel (Build Command), он:
  1. находит рабочий адрес session-пулера Supabase (aws-0/aws-1, порт 5432; прямой хост - запасной);
  2. выполняет ``manage.py migrate`` под ролью владельца;
  3. проверяет RLS под ролью приложения (``check_rls``) - сборка падает, если проверка не пройдена;
  4. создаёт первую (вымышленную) компанию командой ``bootstrap_company``.

Секреты читаются только из окружения и НИКОГДА не печатаются (печатается лишь выбранный хост).
Режим transaction-пулера (порт 6543) не используется и запрещён защитой config.dbguard.
Подробности: docs/ops/VERCEL.md.
"""

import os
import subprocess
import sys
from urllib.parse import quote

REQUIRED = ("SB_REF", "SB_REGION", "OWNER_PW", "APP_PW")


def build_url(role: str, password: str, host: str, port: int, ref: str, dbname: str = "postgres"):
    """Строка подключения. Для пулера Supavisor имя пользователя - ``роль.ref``."""
    user = f"{role}.{ref}" if "pooler" in host else role
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{dbname}?sslmode=require"
    )


def candidate_hosts(ref: str, region: str):
    """Сначала session-пулер (IPv4), затем прямой хост (на бесплатном плане - IPv6)."""
    return [
        f"aws-0-{region}.pooler.supabase.com",
        f"aws-1-{region}.pooler.supabase.com",
        f"db.{ref}.supabase.co",
    ]


def probe(url: str):
    """(ok, короткое описание ошибки без секретов)."""
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=10) as conn:
            conn.execute("select 1")
        return True, ""
    except Exception as exc:  # noqa: BLE001 - нужен любой сбой подключения
        return False, type(exc).__name__ + ": " + str(exc).splitlines()[0][:120]


def run_manage(args, database_url: str, extra_env=None):
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": database_url,
            "DJANGO_SERVERLESS": "true",
            "DJANGO_DEBUG": "false",
            "DATABASE_SSL_REQUIRE": "true",
            "DATABASE_CONN_MAX_AGE": "0",
        }
    )
    env.setdefault("DJANGO_SECRET_KEY", "bootstrap-only-" + "x" * 50)
    if extra_env:
        env.update(extra_env)
    print("$ manage.py", args[0], flush=True)
    subprocess.run([sys.executable, "manage.py", *args], check=True, env=env)


def main() -> int:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        print("Не заданы переменные:", ", ".join(missing))
        return 2
    ref, region = os.environ["SB_REF"], os.environ["SB_REGION"]
    owner_pw, app_pw = os.environ["OWNER_PW"], os.environ["APP_PW"]

    chosen = None
    for host in candidate_hosts(ref, region):
        for port in (5432,):
            ok, why = probe(build_url("logistix_owner", owner_pw, host, port, ref))
            print(f"подключение {host}:{port} -> {'OK' if ok else 'нет: ' + why}", flush=True)
            if ok:
                chosen = (host, port)
                break
        if chosen:
            break
    if not chosen:
        print("Ни один адрес БД не доступен из сборки.")
        return 3
    host, port = chosen
    owner_url = build_url("logistix_owner", owner_pw, host, port, ref)
    app_url = build_url("logistix_app", app_pw, host, port, ref)
    ok, why = probe(app_url)
    print(f"роль приложения на {host}:{port} -> {'OK' if ok else 'нет: ' + why}", flush=True)
    if not ok:
        return 4

    run_manage(["migrate", "--noinput"], owner_url)
    run_manage(["check_rls"], app_url)

    login = os.environ.get("DEMO_OWNER_LOGIN")
    password = os.environ.get("DEMO_OWNER_PW")
    if login and password:
        run_manage(
            [
                "bootstrap_company",
                "--name",
                os.environ.get("DEMO_COMPANY_NAME", "Демо Логистикс"),
                "--owner-login",
                login,
                "--owner-name",
                os.environ.get("DEMO_OWNER_NAME", "Демо Владелец"),
                "--modules",
                "forwarding",
                "--password-env",
                "DEMO_OWNER_PW",
            ],
            app_url,
        )
    print(f"ГОТОВО: рабочий хост {host}:{port}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
