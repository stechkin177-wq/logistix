import importlib
from datetime import datetime
from datetime import timezone as dt_tz

import pytest
import time_machine

from apps.core.models import Company, Role
from apps.core.numbering.models import NumberingRule
from apps.core.numbering.services import peek_number
from apps.core.permissions_catalog import ALL_PERMISSIONS, SYSTEM_ROLES
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

NEW_KINDS = {
    "contract": "Д-{year}-{index}",
    "act": "АКТ-{year}-{index}",
    "carrier_order": "ЗП-{year}-{index}",
    "cmr": "CMR-{year}-{index}",
    "letter": "ИСХ-{year}-{index}",
}
DOC_CODES = ["documents.view", "documents.create", "documents.update", "documents.delete"]


def test_documents_section_in_catalog():
    assert "documents.update" in ALL_PERMISSIONS
    assert len(ALL_PERMISSIONS) == 72  # 70 + audit.view + labels.manage


def test_roles_documents_rights():
    manager = SYSTEM_ROLES["Менеджер"]
    assert "documents.view" in manager and "documents.create" in manager
    assert "documents.update" not in manager
    observer = SYSTEM_ROLES["Наблюдатель"]
    assert "documents.view" in observer and "documents.create" not in observer
    assert not [p for p in SYSTEM_ROLES["Механик"] if p.startswith("documents.")]
    for name in ("Бухгалтер", "Диспетчер"):
        assert "documents.view" in SYSTEM_ROLES[name]
        assert "documents.create" in SYSTEM_ROLES[name]
    assert set(DOC_CODES) <= set(SYSTEM_ROLES["Администратор"])


def test_new_company_has_document_numbering(company):
    with time_machine.travel(datetime(2026, 6, 1, 12, 0, tzinfo=dt_tz.utc), tick=False):
        with tenant_context(company.id):
            rules = {r.kind: r for r in NumberingRule.objects.all()}
            for kind, template in NEW_KINDS.items():
                assert (rules[kind].template, rules[kind].digits) == (template, 5)
                assert rules[kind].next_value == 1
            assert peek_number("act") == "АКТ-2026-00001"


def test_company_created_signal_sent(django_user_model):
    from apps.core.services import create_company_with_defaults
    from apps.core.signals import company_created

    received = []

    def handler(sender, company, **kwargs):
        received.append(company)

    company_created.connect(handler)
    try:
        owner = django_user_model.objects.create_user(
            email="sig@example.com", password="pw-12345-xyz"
        )
        created = create_company_with_defaults("Сигнал", owner, ["forwarding"])
    finally:
        company_created.disconnect(handler)
    assert received == [created]


def test_backfill_adds_rights_and_rules_for_existing_company(company):
    mod = importlib.import_module("apps.core.migrations.0010_documents_permissions_numbering")
    from django.apps import apps as django_apps

    with tenant_context(company.id):
        mgr = Role.objects.get(name="Менеджер")
        mgr.permissions = [p for p in mgr.permissions if not p.startswith("documents.")]
        mgr.save()
        custom = Role.objects.create(name="Свои", permissions=["orders.view"], is_system=False)
        NumberingRule.all_objects.filter(kind__in=NEW_KINDS).delete()
    mod.run_backfill(django_apps)
    mod.run_backfill(django_apps)  # идемпотентно
    with tenant_context(company.id):
        mgr.refresh_from_db()
        custom.refresh_from_db()
        assert mgr.permissions.count("documents.view") == 1
        assert mgr.permissions.count("documents.create") == 1
        assert "documents.update" not in mgr.permissions
        admin = Role.objects.get(name="Администратор")
        assert all(admin.permissions.count(c) == 1 for c in DOC_CODES)
        assert custom.permissions == ["orders.view"]
        for kind in NEW_KINDS:
            assert NumberingRule.objects.filter(kind=kind).count() == 1
        assert Company.objects.count() >= 1
