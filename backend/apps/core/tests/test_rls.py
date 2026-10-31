"""RLS в PostgreSQL - вторая линия изоляции компаний.

Суперпользователь обходит RLS даже с FORCE, поэтому проверки принуждения идут под
ролью приложения logistix_app (SET LOCAL ROLE внутри транзакции теста), а каждый такой
блок сначала убеждается, что текущая роль действительно не суперпользователь и не
BYPASSRLS (защита от ложного прохождения).
"""

import threading
from contextlib import contextmanager
from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from django.db import ProgrammingError, connection, connections, transaction
from django.db.migrations.state import ProjectState

from apps.core import rls
from apps.core.models import Company, Department, Membership
from apps.core.tenancy import reset_current_company, set_current_company, tenant_context

APP_ROLE = "logistix_app"

CORE_TENANT_TABLES = {
    "core_legalentity",
    "core_department",
    "core_role",
    "core_handbook",
    "core_handbookvalue",
    "core_numberingrule",
    "core_auditlog",
}


@pytest.fixture(autouse=True)
def _reset_tenant():
    set_current_company(None)
    yield
    set_current_company(None)


def prepare_app_role(cursor, role=APP_ROLE, extra=""):
    """Роль (если её нет) и права на схему public. Выполняется суперпользователем."""
    cursor.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
            CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS {extra};
          END IF;
        END
        $$
        """
    )
    cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
    cursor.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")


def current_role_flags(conn=connection):
    with conn.cursor() as c:
        c.execute(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        return c.fetchone()


@contextmanager
def app_role(role=APP_ROLE):
    """До конца блока соединение работает под ролью приложения (SET LOCAL ROLE)."""
    assert connection.in_atomic_block, "SET LOCAL ROLE действует только внутри транзакции"
    with connection.cursor() as c:
        prepare_app_role(c, role)
        c.execute(f"SET LOCAL ROLE {role}")
    user, is_super, bypass = current_role_flags()
    assert (user, is_super, bypass) == (role, False, False), "RLS проверяется не под той ролью"
    try:
        yield
    finally:
        if not connection.needs_rollback:  # иначе роль снимет откат транзакции теста
            with connection.cursor() as c:
                c.execute("RESET ROLE")


def raw(sql, params=None):
    with connection.cursor() as c:
        c.execute(sql, params)
        return c.fetchall()


def guc():
    return raw("SELECT current_setting('app.company_id', true)")[0][0]


@pytest.fixture
def two_companies(db):
    a = Company.objects.create(name="A")
    b = Company.objects.create(name="B")
    for company, names in ((a, ["a1", "a2"]), (b, ["b1", "b2"])):
        for name in names:
            Department.all_objects.create(company=company, name=name)
    return a, b


# --- роль и защита от ложного прохождения ---------------------------------------------


def test_suite_runs_as_superuser_and_app_role_is_not(db):
    assert current_role_flags()[1] is True  # иначе существующие тесты проверяли бы RLS
    with app_role():
        user, is_super, bypass = current_role_flags()
        assert (user, is_super, bypass) == (APP_ROLE, False, False)
    assert current_role_flags()[1] is True


def test_superuser_bypasses_rls_so_enforcement_needs_app_role(two_companies):
    # без контекста суперпользователь видит все 4 строки; под ролью приложения - ни одной
    assert raw("SELECT count(*) FROM core_department")[0][0] == 4
    with app_role():
        assert raw("SELECT count(*) FROM core_department")[0][0] == 0


# --- (a)-(e) принуждение под ролью приложения ------------------------------------------


def test_a_no_tenant_context_sees_no_rows(two_companies):
    with app_role():
        assert raw("SELECT * FROM core_department") == []
        assert list(Department.all_objects.all()) == []


def test_b_context_sees_only_own_rows_even_via_all_objects(two_companies):
    a, b = two_companies
    with app_role(), tenant_context(a.id):
        assert {r[0] for r in raw("SELECT company_id FROM core_department")} == {a.id}
        assert sorted(Department.all_objects.values_list("name", flat=True)) == ["a1", "a2"]
        assert not Department.all_objects.filter(company=b).exists()
    with app_role(), tenant_context(b.id):
        assert sorted(Department.all_objects.values_list("name", flat=True)) == ["b1", "b2"]


def test_c_insert_foreign_company_row_violates_with_check(two_companies):
    a, b = two_companies
    with app_role(), tenant_context(a.id):
        with pytest.raises(ProgrammingError, match="row-level security"):
            with transaction.atomic():
                raw(
                    "INSERT INTO core_department (company_id, name) VALUES (%s, 'x') RETURNING id",
                    [b.id],
                )
        # bulk_create обходит TenantModel.save - ловит только RLS
        with pytest.raises(ProgrammingError, match="row-level security"):
            with transaction.atomic():
                Department.all_objects.bulk_create([Department(company=b, name="y")])
        # своя компания вставляется
        Department.all_objects.bulk_create([Department(company=a, name="a3")])


def test_c_update_and_delete_of_foreign_rows_affect_nothing(two_companies):
    a, b = two_companies
    b1 = Department.all_objects.get(company=b, name="b1")
    a1 = Department.all_objects.get(company=a, name="a1")
    with app_role(), tenant_context(a.id):
        assert Department.all_objects.filter(pk=b1.pk).update(name="hacked") == 0
        with connection.cursor() as c:
            c.execute("UPDATE core_department SET name = 'hacked' WHERE company_id = %s", [b.id])
            assert c.rowcount == 0
            c.execute("DELETE FROM core_department WHERE company_id = %s", [b.id])
            assert c.rowcount == 0
        assert Department.all_objects.filter(company=b).delete()[0] == 0
        # перенос своей строки в чужую компанию запрещён WITH CHECK
        with pytest.raises(ProgrammingError, match="row-level security"):
            with transaction.atomic():
                Department.all_objects.filter(pk=a1.pk).update(company=b)
    assert sorted(Department.all_objects.filter(company=b).values_list("name", flat=True)) == [
        "b1",
        "b2",
    ]


def test_d_leaving_tenant_context_resets_guc(two_companies):
    a, _ = two_companies
    with app_role():
        with tenant_context(a.id):
            assert raw("SELECT count(*) FROM core_department")[0][0] == 2
        assert raw("SELECT count(*) FROM core_department")[0][0] == 0
        assert guc() in ("", None)


def test_e_stale_guc_from_previous_request_does_not_leak(two_companies):
    a, _ = two_companies
    with app_role():
        token = set_current_company(a.id)  # "запрос 1"
        assert raw("SELECT count(*) FROM core_department")[0][0] == 2
        reset_current_company(token)
        # "запрос 2" на том же соединении, компания не установлена
        assert raw("SELECT count(*) FROM core_department")[0][0] == 0
        assert list(Department.all_objects.all()) == []


def test_non_tenant_tables_are_not_restricted(two_companies):
    # Company/Membership читаются до контекста (вход, аутентификация) - без RLS
    with app_role():
        assert Company.objects.count() == 2
        assert raw("SELECT count(*) FROM core_membership")[0][0] == Membership.objects.count()


# --- (f) потоки --------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_f_threads_each_see_only_own_company():
    a = Company.objects.create(name="A")
    b = Company.objects.create(name="B")
    for company, names in ((a, ["a1", "a2"]), (b, ["b1"])):
        for name in names:
            Department.all_objects.create(company=company, name=name)
    with connection.cursor() as c:
        prepare_app_role(c)

    barrier = threading.Barrier(2)
    results, errors = {}, []

    def worker(company_id):
        try:
            with tenant_context(company_id), transaction.atomic():
                with connection.cursor() as c:
                    c.execute(f"SET LOCAL ROLE {APP_ROLE}")
                assert current_role_flags()[1:] == (False, False)
                barrier.wait(timeout=10)  # оба потока внутри своих транзакций одновременно
                names = sorted(Department.all_objects.values_list("name", flat=True))
                barrier.wait(timeout=10)
                results[company_id] = (names, guc())
        except Exception as exc:  # pragma: no cover - сообщение для отладки
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(cid,)) for cid in (a.id, b.id)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert results == {a.id: (["a1", "a2"], str(a.id)), b.id: (["b1"], str(b.id))}


# --- синхронизация GUC с контекстом -------------------------------------------------------


def test_guc_follows_contextvar(db):
    assert guc() in ("", None)
    with tenant_context(5):
        assert guc() == "5"
        with tenant_context(None):
            assert guc() in ("", None)
        assert guc() == "5"
    assert guc() in ("", None)


def test_set_config_issued_only_when_company_changes(db):
    with mock.patch.object(rls, "_set_guc", wraps=rls._set_guc) as spy:
        with tenant_context(11):
            for _ in range(3):
                guc()
            assert spy.call_count == 1
        guc()
        guc()
        assert spy.call_count == 2


def test_set_current_company_needs_no_database():
    # без маркера django_db: любой доступ к БД здесь упал бы
    token = set_current_company(3)
    reset_current_company(token)


def test_savepoint_rollback_does_not_leave_cache_out_of_sync(db):
    """ROLLBACK TO SAVEPOINT откатывает и set_config: кэш не должен считать GUC актуальным."""
    with tenant_context(1):
        assert guc() == "1"
        token = None
        with pytest.raises(ZeroDivisionError):
            with transaction.atomic():
                token = set_current_company(2)
                assert guc() == "2"
                1 / 0
        # контекст всё ещё 2, а PostgreSQL вернул GUC к "1" вместе с откатом
        assert guc() == "2"
        reset_current_company(token)
        assert guc() == "1"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_transaction_rollback_does_not_leave_cache_out_of_sync():
    with tenant_context(1):
        assert guc() == "1"  # автокоммит: значение закреплено в сессии
        token = None
        with pytest.raises(ZeroDivisionError):
            with transaction.atomic():
                token = set_current_company(2)
                assert guc() == "2"
                1 / 0
        assert guc() == "2"
        reset_current_company(token)
        assert guc() == "1"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_reconnect_resyncs():
    with tenant_context(7):
        assert guc() == "7"
        connection.close()
        assert guc() == "7"


def test_wrapper_survives_foreign_execute_wrapper_block(db):
    """Чужой connection.execute_wrapper() снимает последний обёртчик - не наш."""
    calls = []

    def other(execute, sql, params, many, context):
        calls.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(other):
        guc()
    assert calls
    with tenant_context(9):
        assert guc() == "9"


# --- проверка покрытия RLS (страж для будущих TenantModel) -------------------------------


def test_tenant_tables_cover_core_models_and_skip_test_app():
    tables = set(rls.tenant_tables())
    assert CORE_TENANT_TABLES <= tables
    assert not {"core_company", "core_membership", "core_user"} & tables
    assert not any(t.startswith("core_tests_") for t in tables)


def test_every_tenant_table_has_rls(db):
    assert rls.tables_missing_rls() == []


@pytest.mark.parametrize(
    "breakage",
    [
        "ALTER TABLE core_department DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE core_department NO FORCE ROW LEVEL SECURITY",
        "DROP POLICY tenant_isolation ON core_department",
        "ALTER POLICY tenant_isolation ON core_department RENAME TO other_name",
    ],
)
def test_guard_detects_table_without_rls(db, breakage):
    raw_exec(breakage)
    assert rls.tables_missing_rls() == ["core_department"]


def test_guard_detects_new_table_without_rls(db):
    raw_exec("CREATE TABLE rls_probe (id serial PRIMARY KEY, company_id int NOT NULL)")
    assert rls.tables_missing_rls(["rls_probe", "core_role"]) == ["rls_probe"]
    for sql in rls.enable_rls("rls_probe"):
        raw_exec(sql)
    assert rls.tables_missing_rls(["rls_probe"]) == []


def raw_exec(sql):
    with connection.cursor() as c:
        c.execute(sql)


# --- операция миграции ---------------------------------------------------------------------


def _flags(table):
    return raw(
        "SELECT relrowsecurity, relforcerowsecurity, "
        "(SELECT count(*) FROM pg_policies WHERE tablename = %s "
        "AND policyname = 'tenant_isolation') FROM pg_class WHERE relname = %s",
        [table, table],
    )[0]


def test_enable_rls_operation_forwards_and_backwards(db):
    raw_exec("CREATE TABLE rls_probe (id serial PRIMARY KEY, company_id int NOT NULL)")
    op = rls.EnableRLS("rls_probe")
    state = ProjectState()
    with connection.schema_editor(atomic=False) as editor:
        op.database_forwards("core", editor, state, state)
    assert _flags("rls_probe") == (True, True, 1)
    with connection.schema_editor(atomic=False) as editor:
        op.database_backwards("core", editor, state, state)
    assert _flags("rls_probe") == (False, False, 0)
    assert op.reversible
    assert op.deconstruct() == ("apps.core.rls.EnableRLS", ["rls_probe"], {})


def test_enable_rls_operation_resolves_model_label(db):
    from django.db.migrations.loader import MigrationLoader

    state = MigrationLoader(connection).project_state()
    op = rls.EnableRLS("core.Department")
    with connection.schema_editor(atomic=False) as editor:
        op.database_backwards("core", editor, state, state)
    assert _flags("core_department") == (False, False, 0)
    with connection.schema_editor(atomic=False) as editor:
        op.database_forwards("core", editor, state, state)
    assert _flags("core_department") == (True, True, 1)
    assert "core.Department" in op.describe()


def test_policy_expression_is_fail_closed(db):
    qual, check = raw(
        "SELECT qual, with_check FROM pg_policies "
        "WHERE tablename = 'core_department' AND policyname = 'tenant_isolation'"
    )[0]
    for expr in (qual, check):
        assert "NULLIF(current_setting('app.company_id'::text, true), ''::text)" in expr


# --- команда check_rls ----------------------------------------------------------------------


def test_check_rls_fails_for_superuser(db):
    with pytest.raises(CommandError, match="суперпользовател"):
        call_command("check_rls")


def test_check_rls_fails_for_bypassrls_role(db):
    with connection.cursor() as c:
        c.execute("CREATE ROLE logistix_rls_bypass_probe NOSUPERUSER BYPASSRLS")
        c.execute("SET LOCAL ROLE logistix_rls_bypass_probe")
    with pytest.raises(CommandError, match="BYPASSRLS"):
        call_command("check_rls")


def test_check_rls_passes_for_app_role(db, capsys):
    with app_role():
        call_command("check_rls")
    assert "RLS в порядке" in capsys.readouterr().out


def test_check_rls_fails_when_table_lacks_rls(db):
    raw_exec("ALTER TABLE core_role NO FORCE ROW LEVEL SECURITY")
    with app_role():
        with pytest.raises(CommandError, match="core_role"):
            call_command("check_rls")


# --- приложение целиком под ролью приложения ------------------------------------------------


def test_app_flows_work_under_app_role(db, api_client):
    """Создание компании, вход и API работают под ролью без обхода RLS."""
    from apps.core.models import User
    from apps.core.services import create_company_with_defaults
    from conftest import TEST_PASSWORD

    with app_role():
        admin = User.objects.create_user(email="rls-admin@x.kz", password=TEST_PASSWORD)
        company = create_company_with_defaults("RLS Co", admin, ["forwarding"])
        other_admin = User.objects.create_user(email="rls-other@x.kz", password=TEST_PASSWORD)
        create_company_with_defaults("Other Co", other_admin, ["forwarding"])

        resp = api_client.post(
            "/api/auth/login/", {"login": "rls-admin@x.kz", "password": TEST_PASSWORD}
        )
        assert resp.status_code == 200, resp.content
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

        roles = api_client.get("/api/roles/")
        assert roles.status_code == 200, roles.content
        assert len(roles.data["results"] if "results" in roles.data else roles.data) == 7
        created = api_client.post("/api/departments/", {"name": "Склад"})
        assert created.status_code == 201, created.content
        for url in ("/api/handbooks/", "/api/numbering/", "/api/audit/", "/api/users/"):
            r = api_client.get(url)
            assert r.status_code == 200, (url, r.content)
        # без контекста роль приложения не видит ни одной строки компаний
        assert raw("SELECT count(*) FROM core_role")[0][0] == 0
    with tenant_context(company.id):
        assert Department.objects.filter(name="Склад").exists()


def test_failed_statement_after_context_change_keeps_django_error_semantics(two_companies):
    """Компания сменилась внутри упавшей точки сохранения: ROLLBACK TO SAVEPOINT идёт в
    прерванной транзакции, set_config перед ним выполнять нельзя."""
    from django.db import IntegrityError

    a, b = two_companies
    with tenant_context(a.id):
        assert guc() == str(a.id)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with tenant_context(b.id):
                    Department.all_objects.create(company=b, name="b1")  # дубль имени
        assert not connection.needs_rollback
        assert guc() == str(a.id)


def test_server_side_cursor_iterator_and_select_for_update_respect_rls(two_companies):
    a, _ = two_companies
    with app_role(), tenant_context(a.id):
        names = sorted(d.name for d in Department.all_objects.iterator(chunk_size=1))
        assert names == ["a1", "a2"]
        locked = list(Department.all_objects.select_for_update().values_list("name", flat=True))
        assert sorted(locked) == ["a1", "a2"]
