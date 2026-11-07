# ruff: noqa: E501
"""Пошаговая проверка RLS под РЕАЛЬНОЙ ролью logistix_app для finance.0008 и finance.0009 (временная БД).

Основная БД и демо-БД не затрагиваются. Роль logistix_app создаётся настоящим deploy/db-init.sql
(NOSUPERUSER NOBYPASSRLS). Миграции идут ПОШАГОВО; после каждого шага батарея
rls_battery_task_1_4_13.py выполняется под ролью приложения:
  (а) fail closed без контекста (чтение, изменение, удаление, вставка);
  (б) свои данные читаются и ПИШУТСЯ, включая новые колонки (resolution/resolution_data у
      замечания, флаг заморозки и engine_switched_at у настроек);
  (в) чужая компания не видит, не меняет, не удаляет, не вставляет и не переносит строки;
      частичная уникальность 0008 действует в рамках компании;
  (г) после ROLLBACK, отката точки сохранения и при повторном использовании соединения контекст
      не залипает; откат записи новых колонок не оставляет следов;
  (д) FORCE ROW LEVEL SECURITY включён у всех таблиц компаний и действует на владельца (проба).
Дополнительно (на БД с данными): preflight 0008 на искусственных дублях останавливает миграцию и
ничего не удаляет; откат 0009 -> 0008 -> 0007 не теряет прежних данных; повторное применение
проходит, после каждого перехода RLS проверяется заново. Код возврата 0 - всё пройдено.
"""

import json
import os
import sys

import psycopg
from task_1_4_1_common import (
    APP_PASSWORD,
    APP_ROLE,
    BACKEND,
    DEFAULT_URL,
    TempDatabase,
    apply_db_init,
    manage,
    manage_result,
    with_user,
)
from verify_rls_task_1_4_1 import load_module, owner_force_probe

# состояние ДО подзадачи 1.4.13: finance 0006; обработчик настроек выключен (колонок 0009 ещё нет)
SEED = """
import json
from apps.core.models import User
from apps.core.services import create_company_with_defaults
from apps.core.signals import company_created

company_created.receivers = []
out = {}
for key in ("A", "B"):
    user = User.objects.create_user(email=f"{key.lower()}@rls1413.kz", password="s3cret-pass-1")
    out[key] = {"company": create_company_with_defaults(f"Компания {key}", user, ["forwarding"]).id}
print("IDS=" + json.dumps(out))
"""

ISSUE_INSERT = (
    "INSERT INTO finance_financemigrationissue (company_id, issue_type, severity, source_model, "
    "source_id, message, details, status, resolution_note, created_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, '{}', 'open', '', now()) RETURNING id"
)
ISSUES = [  # (ключ компании, тип, источник)
    ("A", "ambiguous_trip_expense", 101),
    ("A", "ambiguous_trip_expense", 102),
    ("A", "shadow_error", 103),
    ("B", "ambiguous_trip_expense", 201),
    ("B", "reconcile_diff", 202),
]


def scalar(url, sql, params=()):
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchone()[0]


def columns(url, table):
    with psycopg.connect(url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table]
        ).fetchall()
    return {r[0] for r in rows}


def applied(url, name):
    return bool(
        scalar(
            url, "SELECT count(*) FROM django_migrations WHERE app='finance' AND name=%s", [name]
        )
    )


def snapshot(url):
    """Содержимое прежних колонок замечаний и настроек (для сравнения до/после миграций)."""
    with psycopg.connect(url, autocommit=True) as conn:
        issues = conn.execute(
            "SELECT id, company_id, issue_type, severity, source_model, source_id, message, status, "
            "resolution_note FROM finance_financemigrationissue ORDER BY id"
        ).fetchall()
        settings = conn.execute(
            "SELECT company_id, engine, cutover_date, base_currency_id, completed_status_id, "
            "allow_backdating FROM finance_companyfinancialsettings ORDER BY company_id"
        ).fetchall()
    return issues, settings


def battery_step(label, owner_url, app_url, battery, ids, probe_module, reports):
    env = {"RLS_STEP": label, "RLS_IDS": json.dumps(ids), "OWNER_URL": owner_url}
    result = manage(app_url, "shell", stdin=battery, env_extra=env)
    report = json.loads(result.split("RLS_REPORT=")[1].splitlines()[0])
    report["force_probe_checks"] = owner_force_probe(owner_url, owner_url, probe_module)
    reports.append(report)
    print(
        f"OK {label}: таблиц компаний {report['tables']}, под ролью logistix_app проверок "
        f"{report['checks'] + report['force_probe_checks']} "
        f"(resolution={report['has_resolution']}, колонки 0009={report['has_switch_columns']}, "
        f"уникальность={report['has_unique']})"
    )


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    battery = (BACKEND / "scripts" / "rls_battery_task_1_4_13.py").read_text()
    reports = []
    with TempDatabase(base_url, "logistix_rls1413") as db:
        owner_url = db.url
        apply_db_init(owner_url)
        app_url = with_user(owner_url, APP_ROLE, APP_PASSWORD)
        with psycopg.connect(owner_url) as conn:
            row = conn.execute(
                "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=%s",
                [APP_ROLE],
            ).fetchone()
        assert row == (False, False, True), f"роль {APP_ROLE}: {row}"

        # состояние до подзадачи: всё, кроме finance.0007+ (M1..M4 уже применены)
        for app in ("core", "billing", "forwarding", "documents"):
            manage(owner_url, "migrate", app, "--noinput")
        manage(owner_url, "migrate", "finance", "0006", "--noinput")
        out = manage(owner_url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        manage(owner_url, "migrate", "finance", "0007", "--noinput")  # M5: настройки компаний
        assert not applied(owner_url, "0008_migration_issue_resolution")
        probe_module = load_module(
            BACKEND / "apps" / "finance" / "migrations" / "0005_income_expense_ledger.py", "m0005"
        )
        assert scalar(owner_url, "SELECT count(*) FROM finance_companyfinancialsettings") == 2

        # данные для проверок: замечания (в том числе спорные строки) обеих компаний
        issue_ids = {"A": [], "B": []}
        with psycopg.connect(owner_url, autocommit=True) as conn:
            for key, issue_type, source in ISSUES:
                new_id = conn.execute(
                    ISSUE_INSERT,
                    [
                        ids[key]["company"],
                        issue_type,
                        "error",
                        "OrderService",
                        source,
                        f"{issue_type} {source}",
                    ],
                ).fetchone()[0]
                issue_ids[key].append(new_id)
        for key in ("A", "B"):
            ids[key]["issues"] = issue_ids[key]
        dumps = {"0007": snapshot(owner_url)}

        # --- preflight 0008 на искусственных дублях (БД с данными): остановка, ничего не удалено ---
        with psycopg.connect(owner_url, autocommit=True) as conn:
            dup = conn.execute(
                ISSUE_INSERT,
                [
                    ids["A"]["company"],
                    "ambiguous_trip_expense",
                    "error",
                    "OrderService",
                    101,
                    "искусственный дубль",
                ],
            ).fetchone()[0]
        rows_before = scalar(owner_url, "SELECT count(*) FROM finance_financemigrationissue")
        done = manage_result(owner_url, "migrate", "finance", "0008", "--noinput")
        assert done.returncode != 0, "0008 должна остановиться на дублях"
        assert "дубли проблем ambiguous_trip_expense" in (done.stdout + done.stderr), done.stderr
        assert (
            scalar(owner_url, "SELECT count(*) FROM finance_financemigrationissue") == rows_before
        ), "preflight удалил данные"
        assert "resolution" not in columns(owner_url, "finance_financemigrationissue"), (
            "схема изменена после отказа"
        )
        assert not applied(owner_url, "0008_migration_issue_resolution")
        assert (
            scalar(
                owner_url, "SELECT count(*) FROM finance_financemigrationissue WHERE id=%s", [dup]
            )
            == 1
        )
        print(
            f"OK preflight 0008: дубль замечания остановил миграцию, строк {rows_before} на месте, схема не тронута"
        )
        with psycopg.connect(
            owner_url, autocommit=True
        ) as conn:  # заказчик/оператор разбирает дубль вручную
            conn.execute("DELETE FROM finance_financemigrationissue WHERE id=%s", [dup])
        assert snapshot(owner_url) == dumps["0007"]

        # --- состояние 0007 (до 0008): базовая батарея ---
        battery_step("0007", owner_url, app_url, battery, ids, probe_module, reports)

        # --- 0008 ---
        manage(owner_url, "migrate", "finance", "0008", "--noinput")
        issues7, settings7 = dumps["0007"]
        issues8, settings8 = snapshot(owner_url)
        assert issues8 == issues7 and settings8 == settings7, "0008 изменила прежние данные"
        assert (
            scalar(
                owner_url,
                "SELECT count(*) FROM finance_financemigrationissue WHERE resolution <> '' OR resolution_data <> '{}'::jsonb",
            )
            == 0
        )
        battery_step("0008", owner_url, app_url, battery, ids, probe_module, reports)

        # --- 0009 ---
        manage(owner_url, "migrate", "finance", "0009", "--noinput")
        issues9, settings9 = snapshot(owner_url)
        assert issues9 == issues7 and settings9 == settings7, "0009 изменила прежние данные"
        assert (
            scalar(
                owner_url,
                "SELECT count(*) FROM finance_companyfinancialsettings WHERE financial_writes_frozen OR engine_switched_at IS NOT NULL",
            )
            == 0
        )
        battery_step("0009", owner_url, app_url, battery, ids, probe_module, reports)

        # мутационная проверка: без FORCE батарея обязана упасть (проба чувствительна)
        with psycopg.connect(owner_url, autocommit=True) as conn:
            conn.execute("ALTER TABLE finance_companyfinancialsettings NO FORCE ROW LEVEL SECURITY")
        try:
            battery_step("0009-мутация", owner_url, app_url, battery, ids, probe_module, [])
            raise AssertionError("батарея не заметила снятие FORCE RLS")
        except RuntimeError as exc:
            assert "ENABLE+FORCE RLS" in str(exc), exc
        finally:
            with psycopg.connect(owner_url, autocommit=True) as conn:
                conn.execute(
                    "ALTER TABLE finance_companyfinancialsettings FORCE ROW LEVEL SECURITY"
                )
        print("OK мутация: при снятии FORCE RLS батарея падает")

        # --- откат 0009 -> 0008 (колонки удалены, прежние данные на месте), повтор ---
        with psycopg.connect(
            owner_url, autocommit=True
        ) as conn:  # пользовательские значения в колонках 0008/0009
            conn.execute(
                "UPDATE finance_financemigrationissue SET resolution='manual_expense', "
                "resolution_data='{\"category\": \"OTHER\"}'::jsonb, status='resolved' WHERE id=%s",
                [ids["A"]["issues"][0]],
            )
            conn.execute(
                "UPDATE finance_companyfinancialsettings SET financial_writes_frozen=true WHERE company_id=%s",
                [ids["A"]["company"]],
            )
        resolved_row = [r for r in snapshot(owner_url)[0] if r[0] == ids["A"]["issues"][0]][0]
        manage(owner_url, "migrate", "finance", "0008", "--noinput")
        assert "financial_writes_frozen" not in columns(
            owner_url, "finance_companyfinancialsettings"
        )
        assert "engine_switched_at" not in columns(owner_url, "finance_companyfinancialsettings")
        issues_b, settings_b = snapshot(owner_url)
        assert [r for r in issues_b if r[0] == ids["A"]["issues"][0]] == [resolved_row], (
            "откат 0009 повредил замечания"
        )
        assert settings_b == settings7
        assert (
            scalar(
                owner_url,
                "SELECT resolution FROM finance_financemigrationissue WHERE id=%s",
                [ids["A"]["issues"][0]],
            )
            == "manual_expense"
        )
        print(
            "OK откат 0009 -> 0008: колонки заморозки удалены, замечания и настройки (прежние колонки) без потерь"
        )
        battery_step(
            "0008-после-отката-0009", owner_url, app_url, battery, ids, probe_module, reports
        )

        # --- откат 0008 -> 0007: колонки решения и уникальность убраны, остальные данные на месте ---
        manage(owner_url, "migrate", "finance", "0007", "--noinput")
        cols7 = columns(owner_url, "finance_financemigrationissue")
        assert "resolution" not in cols7 and "resolution_data" not in cols7
        assert (
            scalar(
                owner_url,
                "SELECT count(*) FROM pg_indexes WHERE indexname='finissue_ambiguous_source_uniq'",
            )
            == 0
        )
        issues_c, settings_c = snapshot(owner_url)
        assert [r[:7] + r[7:] for r in issues_c if r[0] != ids["A"]["issues"][0]] == [
            r for r in issues7 if r[0] != ids["A"]["issues"][0]
        ]
        assert [r for r in issues_c if r[0] == ids["A"]["issues"][0]][0][:7] == resolved_row[:7], (
            "откат 0008 повредил замечание"
        )
        assert scalar(owner_url, "SELECT count(*) FROM finance_financemigrationissue") == len(
            ISSUES
        )
        print(
            "OK откат 0008 -> 0007: колонки решения и уникальность убраны, строки замечаний без потерь"
        )
        battery_step("0007-после-отката", owner_url, app_url, battery, ids, probe_module, reports)

        # --- повторное применение 0008 и 0009 на данных ---
        manage(owner_url, "migrate", "finance", "0009", "--noinput")
        issues_d, settings_d = snapshot(owner_url)
        assert issues_d == issues_c and settings_d == settings_c, (
            "повторное применение изменило данные"
        )
        battery_step("0009-повторно", owner_url, app_url, battery, ids, probe_module, reports)

        # --- итоговый контроль покрытия средствами приложения и согласованность моделей ---
        out = manage(
            owner_url,
            "shell",
            stdin="from apps.core.rls import tables_missing_rls\nprint('MISSING=%r' % tables_missing_rls())",
        )
        assert "MISSING=[]" in out, out
        manage(owner_url, "makemigrations", "--check", "--dry-run")
        print("tables_missing_rls() == [] и makemigrations --check чисто после 0009")
    total = sum(r["checks"] + r["force_probe_checks"] for r in reports)
    print(
        f"OK: 1.4.13 RLS под ролью {APP_ROLE} проверена после finance.0008 и finance.0009 (шагов {len(reports)}, проверок {total})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
