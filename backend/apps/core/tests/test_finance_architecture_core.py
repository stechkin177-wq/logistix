"""Core в подзадаче 1.4.1: справочник expense_category, права финансовой архитектуры, изоляция
от приложения finance (миграции M2 и M6)."""

import ast
import importlib
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.core.handbooks.defaults import DEFAULTS
from apps.core.handbooks.models import Handbook, HandbookValue
from apps.core.handbooks.system_codes import SYSTEM_CODES
from apps.core.models import Role
from apps.core.permissions_catalog import (
    ACCOUNTANT_FINANCE_PERMISSIONS,
    ALL_PERMISSIONS,
    EXTRA_PERMISSIONS,
    FINANCE_ARCHITECTURE_PERMISSIONS,
    FINANCE_EXTRA_PERMISSIONS,
    SYSTEM_ROLES,
)
from apps.core.tenancy import tenant_context
from apps.forwarding.tests.test_parties import client_with_role

pytestmark = pytest.mark.django_db

NEW_PERMS = [
    "finance.close_period",
    "finance.reopen_period",
    "finance.adjust_closed",
    "finance.backdate",
    "finance.manage_settings",
]
CATEGORIES = {
    "FUEL": "Топливо",
    "MAINTENANCE": "Техобслуживание",
    "REPAIR": "Ремонт",
    "TIRES": "Шины",
    "ROAD": "Дороги и сборы",
    "DRIVER": "Водитель",
    "INSURANCE": "Страхование",
    "TAX": "Налоги",
    "DEPRECIATION": "Амортизация",
    "ADMINISTRATION": "Административные",
    "OTHER": "Прочее",
}
M2 = importlib.import_module("apps.core.migrations.0013_expense_category_handbook")
M6 = importlib.import_module("apps.core.migrations.0014_finance_architecture_permissions")
VALUES = "/api/handbook-values/"


def categories(company):
    with tenant_context(company.id):
        return {
            v.code: v
            for v in HandbookValue.objects.filter(handbook__code="expense_category").order_by(
                "order"
            )
        }


# --- справочник expense_category: состав, защита, посев ---


def test_registry_contains_expense_category():
    assert SYSTEM_CODES["expense_category"] == frozenset(CATEGORIES)
    assert {v["code"]: v["name"] for v in DEFAULTS["expense_category"]["values"]} == CATEGORIES


def test_new_company_gets_expense_categories(company):
    got = categories(company)
    assert {c: v.name for c, v in got.items()} == CATEGORIES
    assert all(v.is_system for v in got.values())


def test_system_expense_category_codes_are_protected_in_api(admin_client, company):
    pk = categories(company)["FUEL"].pk
    url = f"{VALUES}{pk}/"
    assert admin_client.patch(url, {"code": "GAS"}, format="json").status_code == 400
    assert admin_client.patch(url, {"is_active": False}, format="json").status_code == 400
    assert admin_client.delete(url).status_code == 400
    assert categories(company)["FUEL"].is_active and "FUEL" in categories(company)
    # название редактируется, код остаётся
    ok = admin_client.patch(url, {"name": "ГСМ"}, format="json")
    assert ok.status_code == 200 and ok.json()["name"] == "ГСМ" and ok.json()["code"] == "FUEL"
    # зарезервированный код не присвоить новому значению
    with tenant_context(company.id):
        hb = Handbook.objects.get(code="expense_category")
    dup = admin_client.post(
        VALUES, {"handbook": hb.code, "name": "Ещё топливо", "code": "FUEL"}, format="json"
    )
    assert dup.status_code == 400
    # пользовательская категория без кода допустима
    new = admin_client.post(VALUES, {"handbook": hb.code, "name": "Мойка"}, format="json")
    assert new.status_code == 201, new.content
    assert admin_client.delete(f"{VALUES}{new.json()['id']}/").status_code in (200, 204)


def historical_apps(app, name):
    """Реестр моделей на момент миграции: как при реальном migrate (без менеджеров приложения)."""
    return MigrationExecutor(connection).loader.project_state((app, name)).apps


def run_m2():
    M2.run_backfill(historical_apps("core", "0013_expense_category_handbook"))


def run_m6():
    M6.run_backfill(historical_apps("core", "0014_finance_architecture_permissions"))


def drop_categories(company):
    with tenant_context(company.id):
        from apps.core.handbooks.system_codes import system_values_maintenance

        with system_values_maintenance():
            HandbookValue.all_objects.filter(
                company=company, handbook__code="expense_category"
            ).delete()
            Handbook.all_objects.filter(company=company, code="expense_category").delete()


def test_m2_seeds_existing_company_without_handbook(company):
    drop_categories(company)
    assert categories(company) == {}
    run_m2()
    got = categories(company)
    assert {c: v.name for c, v in got.items()} == CATEGORIES
    assert [v.order for v in got.values()] == list(range(1, 12))
    with tenant_context(company.id):
        hb = Handbook.objects.get(code="expense_category")
    assert (hb.name, hb.group) == ("Категории расходов", "Финансы")


def test_m2_is_idempotent_and_keeps_existing_values(company):
    before = {c: (v.pk, v.name, v.order, v.is_active) for c, v in categories(company).items()}
    run_m2()
    run_m2()
    after = {c: (v.pk, v.name, v.order, v.is_active) for c, v in categories(company).items()}
    assert after == before
    # переименованное и пользовательское значения не трогаются, недостающий код добавляется
    HandbookValue.all_objects.filter(pk=categories(company)["TAX"].pk).update(name="Налоги РК")
    with tenant_context(company.id):
        hb = Handbook.objects.get(code="expense_category")
        custom = HandbookValue.objects.create(handbook=hb, name="Мойка", order=50)
        from apps.core.handbooks.system_codes import system_values_maintenance

        with system_values_maintenance():
            HandbookValue.all_objects.filter(pk=categories(company)["OTHER"].pk).delete()
    run_m2()
    got = categories(company)
    assert got["TAX"].name == "Налоги РК"
    assert set(got) - {""} == set(CATEGORIES)
    assert got["OTHER"].order == 51  # добавлен в конец, существующий порядок не менялся
    with tenant_context(company.id):
        assert HandbookValue.objects.get(pk=custom.pk).name == "Мойка"
        assert Handbook.objects.filter(code="expense_category").count() == 1


def test_m2_does_not_touch_other_company(company, make_company):
    other, _, _ = make_company("Other")
    drop_categories(company)
    snapshot = {c: v.pk for c, v in categories(other).items()}
    run_m2()
    assert {c: v.pk for c, v in categories(other).items()} == snapshot


# --- права финансовой архитектуры: каталог и матрица ---


def test_catalog_contains_five_new_permissions_in_separate_list():
    assert FINANCE_ARCHITECTURE_PERMISSIONS == NEW_PERMS
    assert set(NEW_PERMS) <= set(ALL_PERMISSIONS) and set(NEW_PERMS) <= set(EXTRA_PERMISSIONS)
    # Бухгалтер получил бы лишнее, если бы они попали в FINANCE_EXTRA_PERMISSIONS
    assert not set(NEW_PERMS) & set(FINANCE_EXTRA_PERMISSIONS)
    assert len(ALL_PERMISSIONS) == 60 == len(set(ALL_PERMISSIONS))


def test_default_matrix_of_system_roles():
    assert set(NEW_PERMS) <= set(SYSTEM_ROLES["Администратор"])
    assert ACCOUNTANT_FINANCE_PERMISSIONS == [
        "finance.close_period",
        "finance.adjust_closed",
        "finance.backdate",
    ]
    for name, perms in SYSTEM_ROLES.items():
        got = {p for p in perms if p in NEW_PERMS}
        if name == "Администратор":
            assert got == set(NEW_PERMS)
        elif name == "Бухгалтер":
            assert got == {"finance.close_period", "finance.adjust_closed", "finance.backdate"}
            assert "finance.reopen_period" not in perms and "finance.manage_settings" not in perms
        else:
            assert got == set(), name


def test_new_company_roles_follow_matrix(company):
    with tenant_context(company.id):
        for role in Role.objects.filter(is_system=True):
            assert {p for p in role.permissions if p in NEW_PERMS} == {
                p for p in SYSTEM_ROLES[role.name] if p in NEW_PERMS
            }, role.name


def strip_new_permissions(company):
    with tenant_context(company.id):
        for role in Role.objects.all():
            role.permissions = [p for p in role.permissions if p not in NEW_PERMS]
            role.save()
        return Role.objects.create(
            name="Своя роль", permissions=["finance.view", "orders.view"], is_system=False
        )


def test_m6_updates_existing_roles_per_matrix_and_is_idempotent(company, make_company):
    other, _, _ = make_company("Other")
    custom = strip_new_permissions(company)
    run_m6()
    run_m6()  # идемпотентно
    with tenant_context(company.id):
        for role in Role.objects.filter(is_system=True):
            got = [p for p in role.permissions if p in NEW_PERMS]
            assert len(got) == len(set(got)), role.name
            assert set(got) == {p for p in SYSTEM_ROLES[role.name] if p in NEW_PERMS}, role.name
        custom.refresh_from_db()
        assert custom.permissions == ["finance.view", "orders.view"]  # пользовательские - как были
        admin = Role.objects.get(name="Администратор")
        assert admin.permissions[: len(ALL_PERMISSIONS) - 5] == ALL_PERMISSIONS[:-5]
        assert set(admin.permissions) == set(ALL_PERMISSIONS)
    # другая компания не затронута (у неё и так по матрице)
    with tenant_context(other.id):
        assert set(Role.objects.get(name="Администратор").permissions) == set(ALL_PERMISSIONS)


def test_m6_does_not_remove_extra_grants_from_other_roles(company):
    """Миграция только добавляет: права, выданные вручную системной роли, не отзываются."""
    with tenant_context(company.id):
        mech = Role.objects.get(name="Механик")
        mech.permissions = [*mech.permissions, "finance.backdate"]
        mech.save()
    run_m6()
    with tenant_context(company.id):
        assert "finance.backdate" in Role.objects.get(name="Механик").permissions


def test_new_permissions_assignable_to_custom_role_via_api(admin_client, company):
    r = admin_client.post(
        "/api/roles/",
        {"name": "Контролёр", "permissions": ["finance.view", *NEW_PERMS]},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert set(NEW_PERMS) <= set(r.json()["permissions"])
    patched = admin_client.patch(
        f"/api/roles/{r.json()['id']}/",
        {"permissions": ["finance.view", "finance.backdate"]},
        format="json",
    )
    assert patched.status_code == 200 and patched.json()["permissions"] == [
        "finance.view",
        "finance.backdate",
    ]
    unknown = admin_client.post(
        "/api/roles/", {"name": "X", "permissions": ["finance.nope"]}, format="json"
    )
    assert unknown.status_code == 400


def test_cannot_grant_new_permissions_higher_than_own(company):
    with tenant_context(company.id):
        Role.objects.create(
            name="Кадровик",
            permissions=["roles.view", "roles.create", "roles.update", "finance.backdate"],
        )
    _, hr = client_with_role(company, "Кадровик")
    for code in ("finance.reopen_period", "finance.manage_settings", "finance.close_period"):
        r = hr.post("/api/roles/", {"name": f"Р-{code}", "permissions": [code]}, format="json")
        assert r.status_code in (400, 403), code
    ok = hr.post(
        "/api/roles/", {"name": "Р-ok", "permissions": ["finance.backdate"]}, format="json"
    )
    assert ok.status_code == 201, ok.content
    with tenant_context(company.id):
        assert not Role.objects.filter(name__startswith="Р-finance").exists()


def test_accountant_session_has_exactly_three_new_permissions(company):
    _, acc = client_with_role(company, "Бухгалтер")
    me = acc.get("/api/session/")
    assert me.status_code == 200
    perms = set(me.json()["permissions"])
    assert perms & set(NEW_PERMS) == {
        "finance.close_period",
        "finance.adjust_closed",
        "finance.backdate",
    }


# --- core не импортирует finance ---


def test_core_application_code_does_not_import_finance():
    core = Path(django_apps.get_app_config("core").path)
    offenders = []
    for path in core.rglob("*.py"):
        if "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            offenders += [
                f"{path.name}: {n}"
                for n in names
                if n == "apps.finance" or n.startswith("apps.finance.") or n == "finance"
            ]
    assert offenders == []


def test_new_core_migrations_do_not_import_application_code():
    base = Path(M2.__file__).parent
    files = [
        base / "0013_expense_category_handbook.py",
        base / "0014_finance_architecture_permissions.py",
    ]
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                assert not name.startswith("apps"), (path.name, name)
