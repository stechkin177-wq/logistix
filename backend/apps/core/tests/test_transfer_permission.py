"""D3: право consignments.transfer (каталог, роли, миграция, выдача через /api/roles/)."""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.core.models import Role
from apps.core.permissions_catalog import (
    ADMIN_ROLE_NAME,
    ALL_PERMISSIONS,
    EXTRA_PERMISSIONS,
    FINANCE_EXTRA_PERMISSIONS,
    SYSTEM_ROLES,
    TRANSFER_PERMISSIONS,
)
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

PERM = "consignments.transfer"
migration = importlib.import_module("apps.core.migrations.0019_transfer_permission")


def test_permission_in_separate_catalog_list():
    assert TRANSFER_PERMISSIONS == [PERM]
    assert PERM in ALL_PERMISSIONS
    assert PERM not in EXTRA_PERMISSIONS  # отдельный список, не общие extra-списки
    assert PERM not in FINANCE_EXTRA_PERMISSIONS
    assert len(ALL_PERMISSIONS) == len(set(ALL_PERMISSIONS))


HOLDERS = {ADMIN_ROLE_NAME, "Менеджер", "Диспетчер"}


def test_admin_manager_dispatcher_have_it_by_default():
    holders = {name for name, perms in SYSTEM_ROLES.items() if PERM in perms}
    assert holders == HOLDERS


def test_new_company_roles_follow_matrix(make_company):
    company, _, _ = make_company("Roles")
    with tenant_context(company.id):
        for role in Role.objects.filter(is_system=True):
            assert (PERM in role.permissions) == (role.name in HOLDERS), role.name


def test_migration_adds_permission_to_three_roles_and_is_idempotent(make_company):
    company, _, _ = make_company("Mig")
    with tenant_context(company.id):
        custom = Role.objects.create(name="Свои права", permissions=["orders.view"])
        for role in Role.objects.filter(is_system=True):
            role.permissions = [p for p in role.permissions if p != PERM]
            role.save(update_fields=["permissions"])
        before = {r.name: list(r.permissions) for r in Role.objects.all()}
    migration.run_backfill(django_apps)
    migration.run_backfill(django_apps)
    with tenant_context(company.id):
        for role in Role.objects.all():
            if role.is_system and role.name in HOLDERS:
                assert role.permissions.count(PERM) == 1
                assert role.permissions[:-1] == before[role.name]
            else:
                assert role.permissions == before[role.name], role.name
        assert Role.objects.get(pk=custom.pk).permissions == ["orders.view"]


def test_admin_can_assign_permission_to_another_role(admin_client):
    created = admin_client.post(
        "/api/roles/",
        {"name": "Руководитель", "permissions": [PERM, "consignments.view"]},
        format="json",
    )
    assert created.status_code == 201 and PERM in created.data["permissions"]
    patched = admin_client.patch(
        f"/api/roles/{created.data['id']}/", {"permissions": ["consignments.view"]}, format="json"
    )
    assert patched.status_code == 200 and PERM not in patched.data["permissions"]
    again = admin_client.patch(
        f"/api/roles/{created.data['id']}/", {"permissions": [PERM]}, format="json"
    )
    assert again.status_code == 200 and again.data["permissions"] == [PERM]


def test_cannot_grant_permission_you_do_not_have(make_company):
    from rest_framework.test import APIClient

    from apps.core.api.auth import issue_tokens
    from apps.core.models import Membership, User
    from apps.core.tenancy import set_current_company

    company, _, _ = make_company("Grant")
    user = User.objects.create_user(email="roles-only@grant.kz", password="x")
    with tenant_context(company.id):
        role = Role.objects.create(
            name="Менеджер ролей", permissions=["roles.view", "roles.create", "roles.update"]
        )
    Membership.objects.create(user=user, company=company, role=role, is_active=True)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    set_current_company(None)
    denied = api.post("/api/roles/", {"name": "Хитрость", "permissions": [PERM]}, format="json")
    assert denied.status_code == 403
    assert PERM in denied.json()["detail"]
    ok = api.post("/api/roles/", {"name": "Обычная", "permissions": ["roles.view"]}, format="json")
    assert ok.status_code == 201
    escalate = api.patch(f"/api/roles/{ok.data['id']}/", {"permissions": [PERM]}, format="json")
    assert escalate.status_code == 403
