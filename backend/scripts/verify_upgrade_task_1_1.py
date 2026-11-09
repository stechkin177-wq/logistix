"""Проверка обновления с состояния ДО задачи 1.1 на отдельной временной БД (воспроизводимо).

Шаги: создать БД; применить миграции до core.0010 и forwarding.0005; создать данные
(компания со стандартными статусами рейса, компания с переименованным статусом, рейсы с price,
роли); применить новые миграции и проверить результат; откатить новые миграции
(forwarding -> 0005, core -> 0010), применить снова и проверить повторно; удалить БД.

Запуск: ``python scripts/verify_upgrade_task_1_1.py`` (нужны права CREATE DATABASE; основная БД
и демо-БД не затрагиваются). Код возврата 0 - все проверки пройдены.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_URL = "postgres://logistix:logistix@127.0.0.1:5432/logistix"
REVERT = "trips.revert_completed"


def with_db(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def manage(url: str, *args: str, stdin: str | None = None) -> str:
    env = {**os.environ, "DJANGO_DEBUG": "true", "DATABASE_URL": url}
    done = subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=BACKEND,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError(f"manage.py {' '.join(args)} failed:\n{done.stdout}\n{done.stderr}")
    return done.stdout


SEED = """
import json
from apps.core.models import User
from apps.core.services import create_company_with_defaults
from apps.core.handbooks import defaults
from apps.core.signals import company_created
# состояние ДО подзадачи 1.4.1: нет справочника категорий и обработчика финансовых настроек
defaults.DEFAULTS.pop("expense_category", None)
company_created.receivers = []
# состояние ДО CompanyModule (core.0016): модули пишутся только в Company.modules
from apps.core import services as core_services
from apps.core.models import Company as _Company


def _legacy_modules(company, modules, **kwargs):
    _Company.objects.filter(pk=company.pk).update(modules=list(modules))
    company.modules = list(modules)
    return list(modules)


core_services.set_company_modules = _legacy_modules
out = {}
for key, email in (("standard", "std@upgrade.kz"), ("renamed", "ren@upgrade.kz")):
    user = User.objects.create_user_schema_agnostic(email=email, password="s3cret-pass-1")
    out[key] = create_company_with_defaults(key, user, ["forwarding"]).id
print("IDS=" + json.dumps(out))
"""


def seed_old_state(conn, ids: dict) -> dict:
    """Приводит данные к виду ДО задачи 1.1: статусы рейса без кодов, права без нового."""
    trips = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='forwarding_trip' AND column_name='completed_at'"
        )
        assert cur.fetchone() is None, "исходное состояние должно быть ДО forwarding.0007"
        cur.execute("SELECT count(*) FROM django_migrations WHERE app='core' AND name LIKE '0011%'")
        assert cur.fetchone()[0] == 0, "исходное состояние должно быть ДО core.0011"
        for key, company_id in ids.items():
            cur.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id)])
            cur.execute(
                "UPDATE core_handbookvalue SET code='' WHERE company_id=%s AND handbook_id IN "
                "(SELECT id FROM core_handbook WHERE company_id=%s AND code='trip_status')",
                [company_id, company_id],
            )
            if key == "renamed":
                cur.execute(
                    "UPDATE core_handbookvalue SET name='Разгрузка' WHERE company_id=%s "
                    "AND name='Выгрузка'",
                    [company_id],
                )
            cur.execute(
                "UPDATE core_role SET permissions = COALESCE((SELECT jsonb_agg(p) FROM "
                "jsonb_array_elements(permissions) p WHERE p <> to_jsonb(%s::text)), '[]'::jsonb) "
                "WHERE company_id=%s",
                [REVERT, company_id],
            )
            cur.execute(
                "INSERT INTO core_role (company_id, name, is_system, permissions) "
                "VALUES (%s, 'Своя роль', false, %s::jsonb)",
                [company_id, json.dumps(["trips.view", "trips.update"])],
            )
            cur.execute(
                "SELECT v.id FROM core_handbookvalue v JOIN core_handbook h ON h.id=v.handbook_id "
                "WHERE v.company_id=%s AND h.code='trip_status' AND v.name='Планируется'",
                [company_id],
            )
            status_id = cur.fetchone()[0]
            cur.execute(
                "SELECT v.id FROM core_handbookvalue v JOIN core_handbook h ON h.id=v.handbook_id "
                "WHERE v.company_id=%s AND h.code='currency' AND v.name='Тенге'",
                [company_id],
            )
            currency_id = cur.fetchone()[0]
            trips[key] = {}
            for number, price in (("T-1", "100.50"), ("T-2", "0.00"), ("T-3", "777777.77")):
                cur.execute(
                    "INSERT INTO forwarding_trip (company_id, number, vehicle_plate, driver_name, "
                    "price, is_consolidated, created_at, updated_at, currency_id, status_id) "
                    "VALUES (%s, %s, '', '', %s, false, now(), now(), %s, %s) RETURNING id",
                    [company_id, number, price, currency_id, status_id],
                )
                trips[key][cur.fetchone()[0]] = price
        cur.execute("SELECT set_config('app.company_id', '', false)")
    conn.commit()
    return trips


def check_new_state(conn, ids: dict, trips: dict, label: str, company_check_output: str) -> None:
    def ok(cond, message):
        if not cond:
            raise AssertionError(f"[{label}] {message}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='forwarding_trip'"
        )
        columns = {r[0] for r in cur.fetchall()}
        ok("price" in columns and "carrier_price" not in columns, "столбец price")
        ok("completed_at" in columns, "столбец completed_at")
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='forwarding_trip'::regclass AND conname='trip_price_gte_0'"
        )
        ok(cur.fetchone() is not None, "ограничение trip_price_gte_0")
        for key, company_id in ids.items():
            cur.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id)])
            cur.execute(
                "SELECT id, price::text, completed_at FROM forwarding_trip WHERE company_id=%s",
                [company_id],
            )
            got = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
            ok(
                {k: v[0] for k, v in got.items()} == trips[key],
                f"price сохранены ({key}): {got} != {trips[key]}",
            )
            ok(all(v[1] is None for v in got.values()), "completed_at пусто у старых рейсов")
            cur.execute(
                "SELECT v.name, v.code FROM core_handbookvalue v JOIN core_handbook h "
                "ON h.id=v.handbook_id WHERE v.company_id=%s AND h.code='trip_status'",
                [company_id],
            )
            codes = dict(cur.fetchall())
            if key == "standard":
                ok(
                    codes
                    == {
                        "Планируется": "PLANNED",
                        "Ожидает выезда": "ASSIGNED",
                        "В пути": "IN_PROGRESS",
                        "Выгрузка": "UNLOADING",
                        "Завершён": "COMPLETED",
                        "Отменён": "CANCELLED",
                    },
                    f"коды стандартной компании: {codes}",
                )
            else:
                ok(codes["Разгрузка"] == "", "переименованный статус остался без кода")
                ok(sum(1 for c in codes.values() if c) == 5, f"остальные пять назначены: {codes}")
            cur.execute(
                "SELECT name, permissions ? %s FROM core_role WHERE company_id=%s",
                [REVERT, company_id],
            )
            roles = dict(cur.fetchall())
            ok(roles.pop("Администратор") is True, "Администратор получил право")
            ok(not any(roles.values()), f"прочие роли без права: {roles}")
        cur.execute("SELECT set_config('app.company_id', '', false)")
    conn.rollback()  # читающая транзакция не должна держать блокировки на время отката миграций
    ok("UNLOADING: НЕ назначен" in company_check_output, "переименованная компания в отчёте")


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    name = f"logistix_upgrade_check_{uuid.uuid4().hex[:8]}"
    admin = psycopg.connect(with_db(base_url, "postgres"), autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    url = with_db(base_url, name)
    try:
        # 1) состояние ДО задачи 1.1
        manage(url, "migrate", "core", "0010", "--noinput")
        manage(url, "migrate", "billing", "--noinput")
        manage(url, "migrate", "forwarding", "0005", "--noinput")
        manage(url, "migrate", "finance", "0003", "--noinput")
        manage(url, "migrate", "documents", "--noinput")
        out = manage(url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        conn = psycopg.connect(url)
        trips = seed_old_state(conn, ids)
        trips = {k: {int(i): p for i, p in v.items()} for k, v in trips.items()}
        # 2) обновление
        manage(url, "migrate", "--noinput")
        report = manage(url, "check_system_status_codes", "--company", str(ids["renamed"]))
        check_new_state(conn, ids, trips, "после обновления", report)
        # 3) откат новых миграций и повторное применение
        manage(url, "migrate", "forwarding", "0005", "--noinput")
        manage(url, "migrate", "core", "0010", "--noinput")
        manage(url, "migrate", "--noinput")
        report = manage(url, "check_system_status_codes", "--company", str(ids["renamed"]))
        check_new_state(conn, ids, trips, "после отката и повторного применения", report)
        conn.close()
        print("OK: обновление, откат и повторное применение проверены")
        return 0
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


if __name__ == "__main__":
    sys.exit(main())
