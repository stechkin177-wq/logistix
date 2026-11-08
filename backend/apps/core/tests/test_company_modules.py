"""A2: CompanyModule - источник правды, Company.modules - проекция; миграции данных."""

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, transaction

from apps.billing.models import Plan
from apps.core import module_catalog
from apps.core.models import Company, CompanyModule
from apps.core.module_services import (
    VALID_MODULES,
    effective_module_codes,
    enabled_module_codes,
    set_company_modules,
    with_default_companions,
)
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

backfill = importlib.import_module("apps.core.migrations.0017_company_modules_backfill")
plan_migration = importlib.import_module(
    "apps.billing.migrations.0003_plan_finance_documents_modules"
)


def rows(company):
    with tenant_context(company.id):
        return {r.module_code: r.enabled for r in CompanyModule.objects.all()}


def assert_projection(company):
    company.refresh_from_db()
    assert company.modules == enabled_module_codes(company.id)


def test_valid_modules_is_non_core_catalog_and_import_compat():
    from apps.core.services import VALID_MODULES as imported

    assert imported is VALID_MODULES or imported == VALID_MODULES
    assert VALID_MODULES == module_catalog.non_core_codes()
    assert "core" not in VALID_MODULES
    assert {"forwarding", "fleet", "finance", "documents"} <= VALID_MODULES


def test_new_forwarding_company_gets_finance_and_documents(make_company):
    company, _, _ = make_company("F", modules=["forwarding"])
    assert rows(company) == {"forwarding": True, "finance": True, "documents": True}
    assert_projection(company)
    assert company.modules == ["forwarding", "finance", "documents"]


def test_new_fleet_only_company_has_only_fleet(make_company):
    company, _, _ = make_company("Fl", modules=["fleet"])
    assert rows(company) == {"fleet": True}
    assert_projection(company)


def test_core_is_never_stored(make_company):
    company, _, _ = make_company("C", modules=["forwarding", "fleet"])
    assert "core" not in rows(company)
    with pytest.raises(ValueError):
        set_company_modules(company, ["core"])


def test_with_default_companions_order():
    assert with_default_companions(["forwarding", "fleet"]) == [
        "forwarding",
        "fleet",
        "logistics",
        "finance",
        "documents",
    ]
    assert with_default_companions(["fleet"]) == ["fleet"]


def test_create_company_rejects_unmet_requirements(admin_user):
    with pytest.raises(ValueError, match="зависимости"):
        create_company_with_defaults("Bad", admin_user, ["gps"])


def test_projection_always_matches_company_module(make_company):
    company, admin, _ = make_company("P", modules=["forwarding", "fleet"])
    sequences = [
        ["forwarding"],
        [],
        ["fleet", "documents"],
        ["forwarding", "finance", "fleet", "documents"],
        ["finance", "forwarding"],
        [],
    ]
    for seq in sequences:
        result = set_company_modules(company, seq, user=admin, reason="тест")
        assert result == enabled_module_codes(company.id)
        assert set(result) == set(seq)
        assert_projection(company)
        assert company.modules == result


def test_disable_keeps_row_and_reenable_reuses_it(make_company):
    company, admin, _ = make_company("R", modules=["forwarding"])
    with tenant_context(company.id):
        before = CompanyModule.objects.get(module_code="documents").pk
    set_company_modules(company, ["forwarding", "finance"], user=admin, reason="выкл")
    with tenant_context(company.id):
        row = CompanyModule.objects.get(module_code="documents")
        assert row.enabled is False and row.disabled_by == admin and row.reason == "выкл"
        assert row.disabled_at is not None
    set_company_modules(company, ["forwarding", "finance", "documents"], user=admin)
    with tenant_context(company.id):
        row = CompanyModule.objects.get(module_code="documents")
        assert row.pk == before and row.enabled and row.enabled_by == admin
        assert CompanyModule.objects.filter(module_code="documents").count() == 1


def test_unique_company_module_code(make_company):
    company, _, _ = make_company("U", modules=["forwarding"])
    with tenant_context(company.id), pytest.raises(IntegrityError), transaction.atomic():
        CompanyModule.objects.create(module_code="forwarding")


def test_set_modules_is_atomic_with_projection(make_company, monkeypatch):
    company, admin, _ = make_company("A", modules=["forwarding"])
    from apps.core import module_services

    def boom(_company):
        raise RuntimeError("сбой проекции")

    monkeypatch.setattr(module_services, "sync_projection", boom)
    with pytest.raises(RuntimeError):
        set_company_modules(company, ["fleet"], user=admin)
    monkeypatch.undo()
    assert rows(company) == {"forwarding": True, "finance": True, "documents": True}
    assert_projection(company)


def test_effective_modules_is_plan_intersection(make_company):
    company, _, _ = make_company("E", modules=["forwarding", "fleet"])
    assert effective_module_codes(company.id, ["forwarding", "documents"]) == [
        "forwarding",
        "documents",
    ]
    assert effective_module_codes(company.id, []) == []


def test_module_access_is_read_from_company_module(make_company):
    company, _, api = make_company("Acc", modules=["forwarding"])
    assert api.get("/api/session/").json()["modules"] == ["forwarding", "finance", "documents"]
    with tenant_context(company.id):
        CompanyModule.objects.filter(module_code="forwarding").update(enabled=False)
    # Company.modules не менялась вручную: решает именно CompanyModule
    assert "forwarding" in Company.objects.get(pk=company.id).modules
    resp = api.get("/api/clients/")
    assert resp.status_code == 403
    assert resp.json().get("code") == "module_disabled"
    assert api.get("/api/session/").json()["modules"] == ["finance", "documents"]


def test_audit_written_on_change(make_company):
    from apps.core.audit.models import AuditLog

    company, admin, _ = make_company("Au", modules=["forwarding"])
    set_company_modules(company, ["forwarding", "finance"], user=admin, reason="не нужен")
    with tenant_context(company.id):
        entry = AuditLog.objects.filter(object_type="core.companymodule").latest("id")
    assert entry.user == admin
    assert entry.changes["enabled"] == [True, False]
    assert entry.changes["module_code"] == "documents"
    assert entry.changes["reason"] == "не нужен"


# --- миграции данных ----------------------------------------------------------------------------


def _legacy_company(name, modules):
    company = Company.objects.create(name=name, modules=modules)
    return company


def test_backfill_existing_companies():
    fwd = _legacy_company("Fwd", ["forwarding"])
    both = _legacy_company("Both", ["forwarding", "fleet"])
    fleet = _legacy_company("Fleet", ["fleet"])
    junk = _legacy_company("Junk", ["forwarding", "bogus", "core"])
    backfill.run_backfill(django_apps)
    assert rows(fwd) == {"forwarding": True, "finance": True, "documents": True}
    assert rows(both) == {"forwarding": True, "fleet": True, "finance": True, "documents": True}
    assert rows(fleet) == {"fleet": True}
    assert rows(junk) == {"forwarding": True, "finance": True, "documents": True}
    for company in (fwd, both, fleet, junk):
        assert_projection(company)
    both.refresh_from_db()
    assert both.modules[:2] == ["forwarding", "fleet"]  # прежний состав и порядок сохранены
    fwd.refresh_from_db()
    assert fwd.modules == ["forwarding", "finance", "documents"]


def test_backfill_is_idempotent_and_keeps_manual_disable():
    company = _legacy_company("Idem", ["forwarding"])
    backfill.run_backfill(django_apps)
    with tenant_context(company.id):
        CompanyModule.objects.filter(module_code="finance").update(enabled=False)
    company.modules = ["forwarding", "documents"]
    company.save(update_fields=["modules"])
    backfill.run_backfill(django_apps)
    backfill.run_backfill(django_apps)
    assert rows(company) == {"forwarding": True, "finance": False, "documents": True}
    assert_projection(company)
    with tenant_context(company.id):
        assert CompanyModule.objects.count() == 3


def test_backfill_reverse_removes_only_migrated_rows():
    old = _legacy_company("Old", ["forwarding"])
    backfill.run_backfill(django_apps)
    with tenant_context(old.id):
        row = CompanyModule.objects.get(module_code="finance")
        row.reason = "изменено пользователем"
        row.save(update_fields=["reason"])
    backfill.run_reverse(django_apps)
    # строки, правленные пользователем, остаются; перенесённые миграцией удалены
    assert rows(old) == {"finance": True}
    old.refresh_from_db()
    assert "documents" not in old.modules
    backfill.run_backfill(django_apps)  # повтор после отката
    assert set(rows(old)) >= {"forwarding", "finance", "documents"}


def test_plan_migration_adds_finance_documents_idempotently():
    Plan.objects.all().delete()
    fw = Plan.objects.create(code="p1", name="p1", billing_type="monthly", modules=["forwarding"])
    fl = Plan.objects.create(code="p2", name="p2", billing_type="monthly", modules=["fleet"])
    both = Plan.objects.create(
        code="p3", name="p3", billing_type="monthly", modules=["forwarding", "finance", "fleet"]
    )
    for _ in range(2):
        plan_migration.forwards(django_apps, None)
    fw.refresh_from_db(), fl.refresh_from_db(), both.refresh_from_db()
    assert fw.modules == ["forwarding", "finance", "documents"]
    assert fl.modules == ["fleet"]
    assert both.modules == ["forwarding", "finance", "fleet", "documents"]
    plan_migration.backwards(django_apps, None)
    fw.refresh_from_db(), fl.refresh_from_db()
    assert fw.modules == ["forwarding"] and fl.modules == ["fleet"]


def test_seeded_plans_include_finance_and_documents():
    for plan in Plan.objects.filter(code__in=["start", "business", "lifetime"]):
        assert {"forwarding", "finance", "documents"} <= set(plan.modules)
