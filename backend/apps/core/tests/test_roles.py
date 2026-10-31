import pytest
from django.db import IntegrityError, transaction

from apps.core.api.auth import issue_tokens
from apps.core.models import Company, Department, LegalEntity, Membership, Role, User
from apps.core.permissions_catalog import ALL_PERMISSIONS, SYSTEM_ROLES
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import get_current_company_id, set_current_company, tenant_context

pytestmark = [pytest.mark.django_db, pytest.mark.urls("apps.core.tests.urls_roles")]

PASSWORD = "s3cret-pass"
ADMIN = "Администратор"


@pytest.fixture(autouse=True)
def _reset_tenant():
    set_current_company(None)
    yield
    set_current_company(None)


def make_user(email):
    return User.objects.create_user(email=email, password=PASSWORD)


@pytest.fixture
def owner_a():
    return make_user("owner-a@x.kz")


@pytest.fixture
def owner_b():
    return make_user("owner-b@x.kz")


@pytest.fixture
def company_a(owner_a):
    return create_company_with_defaults("A", owner_a, ["forwarding"])


@pytest.fixture
def company_b(owner_b):
    return create_company_with_defaults("B", owner_b, ["forwarding", "fleet"])


def client_for(api_client, user, company):
    tokens = issue_tokens(user, company.id)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return api_client


def role_of(company, name):
    return Role.all_objects.get(company=company, name=name)


def add_member(company, role_name, email="m@x.kz", **kw):
    user = User.objects.filter(email=email).first() or make_user(email)
    return Membership.objects.create(
        user=user, company=company, role=role_of(company, role_name), **kw
    )


@pytest.fixture
def admin_client(api_client, owner_a, company_a):
    return client_for(api_client, owner_a, company_a)


# --- каталог ---


def test_catalog_has_48_unique_codes():
    assert len(ALL_PERMISSIONS) == 48 == len(set(ALL_PERMISSIONS))
    assert "orders.create" in ALL_PERMISSIONS and "numbering.delete" in ALL_PERMISSIONS


def test_system_roles_content():
    assert list(SYSTEM_ROLES) == [
        "Администратор",
        "Менеджер",
        "Бухгалтер",
        "Диспетчер",
        "Механик",
        "Наблюдатель",
        "Водитель",
    ]
    assert SYSTEM_ROLES[ADMIN] == ALL_PERMISSIONS
    assert SYSTEM_ROLES["Механик"] == ["trips.view"]
    assert SYSTEM_ROLES["Водитель"] == []
    assert sorted(SYSTEM_ROLES["Наблюдатель"]) == sorted(
        p for p in ALL_PERMISSIONS if p.endswith(".view")
    )
    mgr = set(SYSTEM_ROLES["Менеджер"])
    assert "orders.create" in mgr and "orders.delete" not in mgr and "finance.view" in mgr
    assert "finance.create" not in mgr and "trash.view" in mgr and "handbooks.view" in mgr
    acc = set(SYSTEM_ROLES["Бухгалтер"])
    assert "finance.delete" in acc and "orders.view" in acc and "orders.update" not in acc
    disp = set(SYSTEM_ROLES["Диспетчер"])
    assert "trips.update" in disp and "clients.view" in disp and "clients.create" not in disp
    assert set(SYSTEM_ROLES["Менеджер"]) | acc | disp <= set(ALL_PERMISSIONS)


# --- create_company_with_defaults ---


def test_company_gets_seven_system_roles(company_a):
    roles = Role.all_objects.filter(company=company_a)
    assert roles.count() == 7
    assert all(r.is_system for r in roles)
    assert role_of(company_a, ADMIN).permissions == ALL_PERMISSIONS


def test_company_defaults_legal_entity_and_owner_membership(company_a, owner_a):
    le = LegalEntity.all_objects.get(company=company_a)
    assert le.name == "A" and le.is_default
    m = Membership.objects.get(user=owner_a, company=company_a)
    assert m.is_active and m.role.name == ADMIN


def test_create_company_leaves_no_context(owner_a):
    create_company_with_defaults("Z", owner_a, ["fleet"])
    assert get_current_company_id() is None


def test_create_company_keeps_outer_context(owner_a):
    with tenant_context(12345):
        create_company_with_defaults("Z", owner_a, ["fleet"])
        assert get_current_company_id() == 12345


@pytest.mark.parametrize("modules", [[], ["bogus"], ["forwarding", "x"]])
def test_create_company_validates_modules(owner_a, modules):
    with pytest.raises(ValueError):
        create_company_with_defaults("Bad", owner_a, modules)
    assert not Company.objects.filter(name="Bad").exists()


def test_create_company_is_atomic(owner_a, company_a):
    # Тот же владелец уже член A; второй вызов не должен оставлять мусор при сбое
    with pytest.raises(ValueError):
        create_company_with_defaults("Half", owner_a, ["nope"])
    assert not Role.all_objects.filter(company__name="Half").exists()


def test_role_name_unique_per_company(company_a):
    with pytest.raises(IntegrityError), transaction.atomic():
        Role.all_objects.create(company=company_a, name="Менеджер", permissions=[])
    Department.all_objects.create(company=company_a, name="Склад")
    with pytest.raises(IntegrityError), transaction.atomic():
        Department.all_objects.create(company=company_a, name="Склад")


# --- permission_required ---


def test_permission_required_unknown_code_raises_at_import():
    from apps.core.api_permissions import permission_required

    with pytest.raises(ValueError):
        permission_required("orders.creat")


def test_manager_without_permission_gets_403(api_client, company_a):
    role = Role.all_objects.create(
        company=company_a, name="Читатель заказов", permissions=["orders.view"]
    )
    user = make_user("mgr@x.kz")
    Membership.objects.create(user=user, company=company_a, role=role)
    client_for(api_client, user, company_a)
    assert api_client.post("/api/_probe/orders/").status_code == 403


def test_system_manager_lacks_orders_create_only_if_removed(api_client, company_a):
    m = add_member(company_a, "Менеджер")
    client_for(api_client, m.user, company_a)
    assert api_client.post("/api/_probe/orders/").status_code == 200
    m.role = role_of(company_a, "Наблюдатель")
    m.save()
    assert api_client.post("/api/_probe/orders/").status_code == 403


def test_permission_checked_per_request_after_role_change(api_client, company_a):
    role = Role.all_objects.create(company=company_a, name="Спец", permissions=["orders.create"])
    user = make_user("s@x.kz")
    Membership.objects.create(user=user, company=company_a, role=role)
    client_for(api_client, user, company_a)
    assert api_client.post("/api/_probe/orders/").status_code == 200
    role.permissions = []
    role.save()
    assert api_client.post("/api/_probe/orders/").status_code == 403


def test_null_role_has_no_permissions(api_client, company_a):
    user = make_user("n@x.kz")
    Membership.objects.create(user=user, company=company_a, role=None)
    client_for(api_client, user, company_a)
    assert api_client.post("/api/_probe/orders/").status_code == 403
    assert api_client.get("/api/roles/").status_code == 403


def test_unauthenticated_probe_is_401(api_client):
    assert api_client.post("/api/_probe/orders/").status_code == 401


def test_permission_uses_membership_of_token_company(api_client, company_a, company_b):
    user = make_user("two@x.kz")
    Membership.objects.create(user=user, company=company_a, role=role_of(company_a, "Менеджер"))
    Membership.objects.create(user=user, company=company_b, role=role_of(company_b, "Водитель"))
    client_for(api_client, user, company_a)
    assert api_client.post("/api/_probe/orders/").status_code == 200
    client_for(api_client, user, company_b)
    assert api_client.post("/api/_probe/orders/").status_code == 403


# --- API ролей ---


def test_roles_list_and_isolation(admin_client, company_a, company_b):
    r = admin_client.get("/api/roles/")
    assert r.status_code == 200
    assert len(r.data) == 7 and {x["name"] for x in r.data} == set(SYSTEM_ROLES)
    other = role_of(company_b, "Менеджер")
    assert admin_client.get(f"/api/roles/{other.id}/").status_code == 404
    assert (
        admin_client.patch(f"/api/roles/{other.id}/", {"name": "x"}, format="json").status_code
        == 404
    )
    assert admin_client.delete(f"/api/roles/{other.id}/").status_code == 404


def test_role_create_update_delete(admin_client, company_a):
    r = admin_client.post(
        "/api/roles/",
        {"name": "Стажёр", "permissions": ["orders.view", "orders.view"]},
        format="json",
    )
    assert r.status_code == 201
    assert r.data["is_system"] is False and r.data["permissions"] == ["orders.view"]
    rid = r.data["id"]
    r = admin_client.patch(f"/api/roles/{rid}/", {"permissions": ["clients.view"]}, format="json")
    assert r.status_code == 200 and r.data["permissions"] == ["clients.view"]
    assert admin_client.delete(f"/api/roles/{rid}/").status_code == 204
    assert not Role.all_objects.filter(pk=rid).exists()


def test_role_create_ignores_is_system_and_company(admin_client, company_a, company_b):
    r = admin_client.post(
        "/api/roles/",
        {"name": "Хитрый", "permissions": [], "is_system": True, "company": company_b.id},
        format="json",
    )
    assert r.status_code == 201
    role = Role.all_objects.get(pk=r.data["id"])
    assert role.company_id == company_a.id and role.is_system is False


def test_role_rejects_unknown_permissions_and_duplicates(admin_client):
    r = admin_client.post(
        "/api/roles/", {"name": "X", "permissions": ["orders.fly"]}, format="json"
    )
    assert r.status_code == 400 and "permissions" in r.data
    r = admin_client.post("/api/roles/", {"name": "X", "permissions": "orders.view"}, format="json")
    assert r.status_code == 400
    r = admin_client.post("/api/roles/", {"name": "Менеджер", "permissions": []}, format="json")
    assert r.status_code == 400


def test_system_role_protected(admin_client, company_a):
    role = role_of(company_a, "Менеджер")
    r = admin_client.delete(f"/api/roles/{role.id}/")
    assert r.status_code == 400
    r = admin_client.patch(f"/api/roles/{role.id}/", {"name": "Новый"}, format="json")
    assert r.status_code == 400
    r = admin_client.patch(f"/api/roles/{role.id}/", {"permissions": []}, format="json")
    assert r.status_code == 400
    r = admin_client.put(
        f"/api/roles/{role.id}/", {"name": "Менеджер", "permissions": []}, format="json"
    )
    assert r.status_code == 400
    role.refresh_from_db()
    assert role.name == "Менеджер" and role.permissions == SYSTEM_ROLES["Менеджер"]


def test_role_with_members_cannot_be_deleted(admin_client, company_a):
    role = Role.all_objects.create(company=company_a, name="Занятая", permissions=[])
    user = make_user("busy@x.kz")
    Membership.objects.create(user=user, company=company_a, role=role)
    assert admin_client.delete(f"/api/roles/{role.id}/").status_code == 409
    assert Role.all_objects.filter(pk=role.pk).exists()


def test_roles_api_requires_roles_permissions(api_client, company_a):
    m = add_member(company_a, "Менеджер")
    client_for(api_client, m.user, company_a)
    assert api_client.get("/api/roles/").status_code == 403
    assert (
        api_client.post("/api/roles/", {"name": "x", "permissions": []}, format="json").status_code
        == 403
    )
    view_only = Role.all_objects.create(company=company_a, name="RV", permissions=["roles.view"])
    m.role = view_only
    m.save()
    assert api_client.get("/api/roles/").status_code == 200
    assert (
        api_client.post("/api/roles/", {"name": "x", "permissions": []}, format="json").status_code
        == 403
    )


# --- API пользователей ---


def test_users_list_and_isolation(admin_client, company_a, company_b, owner_a):
    other = Membership.objects.get(company=company_b)
    r = admin_client.get("/api/users/")
    assert r.status_code == 200
    assert [x["email"] for x in r.data] == ["owner-a@x.kz"]
    assert r.data[0]["role_name"] == ADMIN
    assert admin_client.get(f"/api/users/{other.id}/").status_code == 404
    assert (
        admin_client.patch(
            f"/api/users/{other.id}/", {"is_active": False}, format="json"
        ).status_code
        == 404
    )


def test_create_new_member_sets_password(admin_client, company_a):
    role = role_of(company_a, "Менеджер")
    r = admin_client.post(
        "/api/users/",
        {"login": "New@X.kz", "password": "very-long-pass-1", "role": role.id, "full_name": "Н"},
        format="json",
    )
    assert r.status_code == 201, r.data
    user = User.objects.get(email="new@x.kz")
    assert user.check_password("very-long-pass-1") and user.full_name == "Н"
    m = Membership.objects.get(user=user, company=company_a)
    assert m.role_id == role.id and m.is_active
    assert "password" not in r.data


def test_create_member_by_phone(admin_client, company_a):
    role = role_of(company_a, "Водитель")
    r = admin_client.post(
        "/api/users/",
        {"login": "8 700 555 11 22", "password": "very-long-pass-1", "role": role.id},
        format="json",
    )
    assert r.status_code == 201, r.data
    assert User.objects.get(phone="+77005551122")


def test_new_user_requires_password(admin_client, company_a):
    role = role_of(company_a, "Менеджер")
    r = admin_client.post("/api/users/", {"login": "np@x.kz", "role": role.id}, format="json")
    assert r.status_code == 400 and "password" in r.data
    assert not User.objects.filter(email="np@x.kz").exists()


def test_attach_existing_user_keeps_password(admin_client, company_a, company_b, owner_b):
    role = role_of(company_a, "Менеджер")
    r = admin_client.post(
        "/api/users/",
        {"login": "OWNER-B@x.kz", "password": "attacker-pass-9", "role": role.id},
        format="json",
    )
    assert r.status_code == 201, r.data
    owner_b.refresh_from_db()
    assert owner_b.check_password(PASSWORD) and not owner_b.check_password("attacker-pass-9")
    assert Membership.objects.filter(user=owner_b, company=company_a).exists()
    assert User.objects.filter(email="owner-b@x.kz").count() == 1


def test_duplicate_member_rejected(admin_client, company_a, owner_a):
    role = role_of(company_a, "Менеджер")
    r = admin_client.post(
        "/api/users/",
        {"login": "owner-a@x.kz", "password": "x" * 12, "role": role.id},
        format="json",
    )
    assert r.status_code == 400


def test_foreign_role_or_department_rejected(admin_client, company_a, company_b):
    foreign_role = role_of(company_b, "Менеджер")
    foreign_dep = Department.all_objects.create(company=company_b, name="Чужой")
    r = admin_client.post(
        "/api/users/",
        {"login": "f@x.kz", "password": "very-long-pass-1", "role": foreign_role.id},
        format="json",
    )
    assert r.status_code in (400, 404) and not User.objects.filter(email="f@x.kz").exists()
    mine = role_of(company_a, "Менеджер")
    r = admin_client.post(
        "/api/users/",
        {
            "login": "f@x.kz",
            "password": "very-long-pass-1",
            "role": mine.id,
            "department": foreign_dep.id,
        },
        format="json",
    )
    assert r.status_code in (400, 404) and not User.objects.filter(email="f@x.kz").exists()
    m = add_member(company_a, "Менеджер")
    for body in ({"role": foreign_role.id}, {"department": foreign_dep.id}):
        r = admin_client.patch(f"/api/users/{m.id}/", body, format="json")
        assert r.status_code in (400, 404)
    m.refresh_from_db()
    assert m.role.company_id == company_a.id and m.department_id is None


def test_is_platform_admin_not_settable(admin_client, company_a):
    role = role_of(company_a, "Менеджер")
    r = admin_client.post(
        "/api/users/",
        {
            "login": "pa@x.kz",
            "password": "very-long-pass-1",
            "role": role.id,
            "is_platform_admin": True,
        },
        format="json",
    )
    assert r.status_code == 400
    assert not User.objects.filter(email="pa@x.kz").exists()
    m = add_member(company_a, "Менеджер")
    r = admin_client.patch(f"/api/users/{m.id}/", {"is_platform_admin": True}, format="json")
    assert r.status_code == 400
    m.user.refresh_from_db()
    assert m.user.is_platform_admin is False


def test_update_role_department_active(admin_client, company_a):
    m = add_member(company_a, "Менеджер")
    dep = Department.all_objects.create(company=company_a, name="Отдел продаж")
    new_role = role_of(company_a, "Бухгалтер")
    r = admin_client.patch(
        f"/api/users/{m.id}/",
        {"role": new_role.id, "department": dep.id, "is_active": False},
        format="json",
    )
    assert r.status_code == 200, r.data
    m.refresh_from_db()
    assert (m.role_id, m.department_id, m.is_active) == (new_role.id, dep.id, False)
    r = admin_client.patch(f"/api/users/{m.id}/", {"department": None}, format="json")
    assert r.status_code == 200
    m.refresh_from_db()
    assert m.department_id is None


def test_last_admin_cannot_be_deactivated_or_demoted(admin_client, company_a, owner_a):
    m = Membership.objects.get(user=owner_a, company=company_a)
    r = admin_client.patch(f"/api/users/{m.id}/", {"is_active": False}, format="json")
    assert r.status_code == 400
    r = admin_client.patch(
        f"/api/users/{m.id}/", {"role": role_of(company_a, "Менеджер").id}, format="json"
    )
    assert r.status_code == 400
    m.refresh_from_db()
    assert m.is_active and m.role.name == ADMIN


def test_admin_can_be_demoted_when_another_active_admin_exists(admin_client, company_a, owner_a):
    second = add_member(company_a, ADMIN, email="adm2@x.kz")
    m = Membership.objects.get(user=owner_a, company=company_a)
    r = admin_client.patch(
        f"/api/users/{m.id}/", {"role": role_of(company_a, "Менеджер").id}, format="json"
    )
    assert r.status_code == 200
    # теперь второй - последний
    client_for(admin_client, second.user, company_a)
    r = admin_client.patch(f"/api/users/{second.id}/", {"is_active": False}, format="json")
    assert r.status_code == 400


def test_inactive_admin_does_not_count(admin_client, company_a, owner_a):
    add_member(company_a, ADMIN, email="adm3@x.kz", is_active=False)
    m = Membership.objects.get(user=owner_a, company=company_a)
    r = admin_client.patch(f"/api/users/{m.id}/", {"is_active": False}, format="json")
    assert r.status_code == 400


def test_users_api_permissions(api_client, company_a):
    m = add_member(company_a, "Менеджер")
    client_for(api_client, m.user, company_a)
    assert api_client.get("/api/users/").status_code == 403
    m.role = role_of(company_a, "Наблюдатель")
    m.save()
    assert api_client.get("/api/users/").status_code == 200
    r = api_client.patch(f"/api/users/{m.id}/", {"is_active": False}, format="json")
    assert r.status_code == 403


# --- отделы ---


def test_departments_crud_and_isolation(admin_client, company_a, company_b):
    r = admin_client.post("/api/departments/", {"name": "Логистика"}, format="json")
    assert r.status_code == 201
    did = r.data["id"]
    assert (
        admin_client.post("/api/departments/", {"name": "Логистика"}, format="json").status_code
        == 400
    )
    r = admin_client.patch(f"/api/departments/{did}/", {"name": "Логисты"}, format="json")
    assert r.status_code == 200 and r.data["name"] == "Логисты"
    assert [d["name"] for d in admin_client.get("/api/departments/").data] == ["Логисты"]
    foreign = Department.all_objects.create(company=company_b, name="Чужой")
    assert admin_client.get("/api/departments/").data != []
    assert admin_client.get(f"/api/departments/{foreign.id}/").status_code == 404
    assert admin_client.delete(f"/api/departments/{foreign.id}/").status_code == 404
    assert admin_client.delete(f"/api/departments/{did}/").status_code == 204


def test_department_delete_unassigns_members(admin_client, company_a):
    dep = Department.all_objects.create(company=company_a, name="Д")
    m = add_member(company_a, "Менеджер", department=dep)
    assert admin_client.delete(f"/api/departments/{dep.id}/").status_code == 204
    m.refresh_from_db()
    assert m.department_id is None
