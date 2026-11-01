import importlib

import pytest

from apps.core.handbooks.models import Handbook, HandbookValue
from apps.core.models import Role
from apps.core.permissions_catalog import ALL_PERMISSIONS, SYSTEM_ROLES
from apps.core.tenancy import tenant_context

EXTRA = ["finance.override_limit", "finance.cancel_invoice"]


def test_extra_codes_in_all_permissions():
    for code in EXTRA:
        assert code in ALL_PERMISSIONS
    assert len(ALL_PERMISSIONS) == len(set(ALL_PERMISSIONS))


def test_admin_and_accountant_have_extra():
    for role in ("Администратор", "Бухгалтер"):
        for code in EXTRA:
            assert code in SYSTEM_ROLES[role]
    for role in ("Менеджер", "Наблюдатель", "Диспетчер"):
        assert not set(EXTRA) & set(SYSTEM_ROLES[role])


@pytest.mark.django_db
def test_new_company_has_vat_handbook(company):
    with tenant_context(company.id):
        hb = Handbook.objects.get(code="vat_rate")
        values = list(HandbookValue.objects.filter(handbook=hb).order_by("order"))
    assert [v.code for v in values] == ["none", "0", "12", "16"]
    assert hb.group == "Финансы"


@pytest.mark.django_db
def test_migration_adds_to_existing_roles(company):
    mod = importlib.import_module("apps.core.migrations.0009_finance_permissions_vat")
    from django.apps import apps as django_apps

    with tenant_context(company.id):
        acc = Role.objects.get(name="Бухгалтер")
        acc.permissions = [p for p in acc.permissions if p not in EXTRA]
        acc.save()
        custom = Role.objects.create(name="Свои", permissions=["orders.view"], is_system=False)
        HandbookValue.all_objects.filter(handbook__code="vat_rate").delete()
        Handbook.all_objects.filter(code="vat_rate").delete()
    mod.run_backfill(django_apps)
    mod.run_backfill(django_apps)  # идемпотентно
    with tenant_context(company.id):
        acc.refresh_from_db()
        custom.refresh_from_db()
        assert all(acc.permissions.count(c) == 1 for c in EXTRA)
        assert custom.permissions == ["orders.view"]
        assert Handbook.objects.filter(code="vat_rate").count() == 1
