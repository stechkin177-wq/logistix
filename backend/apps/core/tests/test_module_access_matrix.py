"""A3: три независимых уровня доступа (тариф x компания x право) на реальных эндпоинтах."""

import itertools

import pytest
from rest_framework.test import APIClient

from apps.billing.models import Plan
from apps.core.api.auth import issue_tokens
from apps.core.models import Membership, Role, User
from apps.core.module_services import enabled_module_codes, set_company_modules
from apps.core.tenancy import set_current_company, tenant_context

pytestmark = pytest.mark.django_db

ENDPOINTS = {
    "logistics": ("/api/clients/", "clients.view"),
    "forwarding": ("/api/carriers/", "carriers.view"),
    "finance": ("/api/finance/invoices/", "finance.view"),
    "documents": ("/api/documents/issued/", "documents.view"),
}
BASE_PLAN = ["fleet"]  # прочие модули тарифа не мешают проверке


_seq = itertools.count(1)


def _client_with_permissions(company, permissions):
    n = next(_seq)
    user = User.objects.create_user(email=f"m{n}@matrix.kz", password="x")
    with tenant_context(company.id):
        role = Role.all_objects.create(
            company=company, name=f"Матрица {n}", permissions=permissions
        )
    Membership.objects.create(user=user, company=company, role=role, is_active=True)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    set_current_company(None)
    return api


@pytest.mark.parametrize("module", sorted(ENDPOINTS))
def test_effective_access_is_plan_and_company_and_permission(make_company, module):
    path, permission = ENDPOINTS[module]
    company, admin, _ = make_company(f"Matrix {module}", modules=["forwarding", "fleet"])
    with_perm = _client_with_permissions(company, [permission])
    without_perm = _client_with_permissions(company, ["trash.view"])
    for in_plan, enabled, has_perm in itertools.product([True, False], repeat=3):
        Plan.objects.filter(code="start").update(
            modules=[*BASE_PLAN, *([module] if in_plan else [])]
        )
        base = ["logistics", "forwarding", "fleet", "finance", "documents"]
        wanted = [m for m in base if m != module]
        set_company_modules(company, [*wanted, *([module] if enabled else [])])
        api = with_perm if has_perm else without_perm
        response = api.get(path)
        label = f"{module}: тариф={in_plan} компания={enabled} право={has_perm}"
        if in_plan and enabled and has_perm:
            assert response.status_code == 200, label
        elif not (in_plan and enabled):
            # уровень модуля проверяется раньше права
            assert response.status_code == 403, label
            assert response.json()["code"] == "module_disabled", label
        else:
            assert response.status_code == 403, label
            assert response.json().get("code") != "module_disabled", label


def test_finance_and_documents_follow_their_own_modules(make_company):
    """Отключение finance не закрывает documents и forwarding (и наоборот)."""
    company, admin, api = make_company("Own", modules=["forwarding"])
    set_company_modules(company, ["forwarding", "documents"])
    assert api.get("/api/finance/invoices/").json()["code"] == "module_disabled"
    assert api.get("/api/documents/issued/").status_code == 200
    assert api.get("/api/clients/").status_code == 200
    set_company_modules(company, ["forwarding", "finance"])
    assert api.get("/api/finance/invoices/").status_code == 200
    assert api.get("/api/documents/issued/").json()["code"] == "module_disabled"
    assert api.get("/api/documents/templates/").json()["code"] == "module_disabled"
    assert api.get("/api/documents/capabilities/").json()["code"] == "module_disabled"
    assert api.get("/api/clients/").status_code == 200


def test_forwarding_off_keeps_finance_and_documents_endpoints_working(make_company):
    company, admin, api = make_company("NoFwd", modules=["forwarding"])
    set_company_modules(company, ["finance", "documents"])
    assert api.get("/api/clients/").json()["code"] == "module_disabled"
    assert api.get("/api/documents/issued/").status_code == 200
    assert api.get("/api/finance/invoices/").status_code == 200


def test_session_modules_are_effective_list_and_format_unchanged(make_company):
    company, admin, api = make_company("Sess", modules=["forwarding", "fleet"])
    Plan.objects.filter(code="start").update(modules=["logistics", "forwarding", "documents"])
    data = api.get("/api/session/").json()
    # список строк, тариф ∩ компания
    assert data["modules"] == ["forwarding", "logistics", "documents"]
    assert isinstance(data["modules"], list) and all(isinstance(m, str) for m in data["modules"])
    assert set(data) == {
        "user",
        "company",
        "companies",
        "role",
        "modules",
        "permissions",
        "branding",
        "subscription",
    }
    assert set(enabled_module_codes(company.id)) >= {"forwarding", "fleet", "finance", "documents"}
