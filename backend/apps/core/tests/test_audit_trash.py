import itertools
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

import pytest
import time_machine
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core import audit, trash
from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog, AuditLogImmutable
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Membership, Role, User
from apps.core.numbering.models import NumberingRule
from apps.core.tenancy import NoTenantContext, get_current_company_id, tenant_context
from apps.core.tests.models import PlainTenant, SoftTenant

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-pass-91"
_n = itertools.count(1)


def rows(company, **filters):
    with tenant_context(company.id):
        return list(AuditLog.objects.filter(**filters).order_by("id"))


def last_row(company, **filters):
    found = rows(company, **filters)
    assert found, f"нет записей аудита {filters}"
    return found[-1]


def role_id(company, name):
    with tenant_context(company.id):
        return Role.objects.get(name=name).pk


def client_with_role(company, role_name):
    n = next(_n)
    user = User.objects.create_user(email=f"u{n}@audit.kz", password=PASSWORD)
    Membership.objects.create(user=user, company=company, role_id=role_id(company, role_name))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return user, client


def make_soft(company, name="x", deleted=False):
    with tenant_context(company.id):
        obj = SoftTenant.objects.create(name=name)
        if deleted:
            obj.delete()
    return obj


@pytest.fixture
def registry():
    saved = dict(trash._registry)
    trash.clear_registry()
    trash.register(SoftTenant, "softs", "clients.view")
    yield
    trash.clear_registry()
    trash._registry.update(saved)


def expire(company):
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))


# --- модель AuditLog ---


def test_auditlog_is_append_only(company, admin_user):
    with tenant_context(company.id):
        row = audit.log("create", admin_user, admin_user)
        row.object_repr = "changed"
        with pytest.raises(AuditLogImmutable):
            row.save()
        with pytest.raises(AuditLogImmutable):
            row.delete()
        assert AuditLog.objects.get(pk=row.pk).object_repr != "changed"


def test_auditlog_indexes_and_ordering():
    cols = {tuple(i.fields) for i in AuditLog._meta.indexes}
    assert ("company", "created_at") in cols
    assert ("company", "object_type", "object_id") in cols
    with connection.cursor() as cur:
        constraints = connection.introspection.get_constraints(cur, AuditLog._meta.db_table)
    assert sum(1 for c in constraints.values() if c["index"]) >= 2
    assert list(AuditLog._meta.ordering) == ["-created_at", "-id"]


# --- audit.log / diff ---


def test_log_basic_fields_from_context(company, admin_user):
    with tenant_context(company.id):
        role = Role.objects.get(name="Менеджер")
        row = audit.log("update", role, admin_user, {"name": ["a", "b"]}, ip="10.0.0.1")
    assert row.company_id == company.id and row.user_id == admin_user.pk
    assert row.action == "update" and row.object_type == "core.role"
    assert row.object_id == str(role.pk) and row.object_repr == "Менеджер"
    assert row.changes == {"name": ["a", "b"]} and row.ip == "10.0.0.1"
    assert row.created_at is not None


def test_log_company_from_object_without_context(company, admin_user):
    with tenant_context(company.id):
        obj = PlainTenant.objects.create(name="p")
    row = audit.log("create", obj, admin_user)
    assert row.company_id == company.id
    assert get_current_company_id() is None


def test_log_fails_closed_without_company(admin_user):
    with pytest.raises(NoTenantContext):
        audit.log("login", admin_user, admin_user)  # у User нет company_id
    with pytest.raises(NoTenantContext):
        audit.log("login", None, admin_user, object_type="x", object_id="1")


def test_log_validates_action(company, admin_user):
    with tenant_context(company.id):
        with pytest.raises(ValueError):
            audit.log("explode", admin_user, admin_user)


def test_log_explicit_object_type_and_id_without_obj(company, admin_user):
    with tenant_context(company.id):
        row = audit.log("delete", None, admin_user, object_type="core.thing", object_id=42)
    assert (row.object_type, row.object_id, row.object_repr) == ("core.thing", "42", "")


def test_log_truncates_repr(company, admin_user):
    with tenant_context(company.id):
        obj = PlainTenant.objects.create(name="n")
        obj.__class__.__str__ = lambda self: "я" * 400
        try:
            row = audit.log("create", obj, admin_user)
        finally:
            del obj.__class__.__str__
    assert len(row.object_repr) == 255


def test_log_masks_sensitive_fields(company, admin_user):
    assert audit.SENSITIVE_FIELDS == {"password", "token", "refresh", "access", "secret"}
    changes = {
        "password": ["old-hash", "new-hash"],
        "name": ["a", "b"],
        "nested": {"token": "abc", "ok": 1, "deep": {"secret": "kept-as-is-too-deep"}},
        "access": "jwt",
    }
    with tenant_context(company.id):
        row = audit.log("update", admin_user, admin_user, changes)
    assert row.changes["password"] == "***" and row.changes["access"] == "***"
    assert row.changes["name"] == ["a", "b"]
    assert row.changes["nested"]["token"] == "***" and row.changes["nested"]["ok"] == 1
    assert changes["password"] == ["old-hash", "new-hash"]  # вход не мутируется


def test_diff_returns_only_changed():
    assert audit.diff({"a": 1, "b": 2}, {"a": 1, "b": 3}) == {"b": [2, 3]}
    assert audit.diff({}, {"a": 1, "z": None}) == {"a": [None, 1]}
    assert audit.diff({"a": 1}, {}) == {"a": [1, None]}
    assert audit.diff({"a": 1}, {"a": 1}) == {}


# --- AuditedMixin: роли, отделы ---


def test_roles_audited(admin_client, company):
    r = admin_client.post(
        "/api/roles/", {"name": "Новая", "permissions": ["clients.view"]}, format="json"
    )
    rid = r.json()["id"]
    row = last_row(company, action="create", object_type="core.role")
    assert row.object_id == str(rid) and row.object_repr == "Новая"
    assert row.changes["name"] == [None, "Новая"]
    assert row.changes["permissions"] == [None, ["clients.view"]]

    admin_client.patch(f"/api/roles/{rid}/", {"name": "Другая"}, format="json")
    row = last_row(company, action="update", object_type="core.role")
    assert row.object_id == str(rid) and row.changes == {"name": ["Новая", "Другая"]}

    assert admin_client.delete(f"/api/roles/{rid}/").status_code == 204
    row = last_row(company, action="delete", object_type="core.role")
    assert row.object_id == str(rid) and row.object_repr == "Другая"


def test_failed_role_delete_writes_nothing(admin_client, company):
    rid = role_id(company, "Менеджер")
    before = len(rows(company))
    assert admin_client.delete(f"/api/roles/{rid}/").status_code in (400, 409)
    assert len(rows(company)) == before


def test_departments_audited(admin_client, company):
    r = admin_client.post("/api/departments/", {"name": "Склад"}, format="json")
    did = r.json()["id"]
    row = last_row(company, action="create", object_type="core.department")
    assert row.object_id == str(did) and row.changes["name"] == [None, "Склад"]
    admin_client.patch(f"/api/departments/{did}/", {"name": "Офис"}, format="json")
    row = last_row(company, action="update", object_type="core.department")
    assert row.changes == {"name": ["Склад", "Офис"]}
    admin_client.delete(f"/api/departments/{did}/")
    row = last_row(company, action="delete", object_type="core.department")
    assert row.object_id == str(did)


# --- пользователи ---


def test_membership_create_audited_without_secrets(admin_client, company):
    rid = role_id(company, "Менеджер")
    r = admin_client.post(
        "/api/users/",
        {"login": "fresh@audit.kz", "password": PASSWORD, "role": rid, "full_name": "Новый"},
        format="json",
    )
    assert r.status_code == 201
    mid = r.json()["id"]
    row = last_row(company, action="create", object_type="core.membership")
    assert row.object_id == str(mid)
    assert row.changes["role_id"] == [None, rid]
    blob = str(row.changes) + row.object_repr
    assert PASSWORD not in blob and "password" not in blob.lower()
    everything = " ".join(str(x.changes) for x in rows(company))
    assert PASSWORD not in everything


def test_membership_update_audited(admin_client, company):
    manager = client_with_role(company, "Менеджер")[0]
    mid = Membership.objects.get(user=manager, company=company).pk
    dept = admin_client.post("/api/departments/", {"name": "Отдел"}, format="json").json()["id"]
    new_role = role_id(company, "Диспетчер")
    r = admin_client.patch(
        f"/api/users/{mid}/",
        {"role": new_role, "department": dept, "is_active": False},
        format="json",
    )
    assert r.status_code == 200
    row = last_row(company, action="update", object_type="core.membership")
    assert row.object_id == str(mid)
    assert row.changes["role_id"] == [role_id(company, "Менеджер"), new_role]
    assert row.changes["department_id"] == [None, dept]
    assert row.changes["is_active"] == [True, False]


# --- справочники, нумерация ---


def test_handbook_values_audited(admin_client, company):
    r = admin_client.post(
        "/api/handbook-values/", {"handbook": "packaging", "name": "Тара"}, format="json"
    )
    vid = r.json()["id"]
    row = last_row(company, action="create", object_type="core.handbookvalue")
    assert row.object_id == str(vid) and row.changes["name"] == [None, "Тара"]
    admin_client.patch(f"/api/handbook-values/{vid}/", {"name": "Тара2"}, format="json")
    row = last_row(company, action="update", object_type="core.handbookvalue")
    assert row.changes == {"name": ["Тара", "Тара2"]}
    assert admin_client.delete(f"/api/handbook-values/{vid}/").status_code == 204
    row = last_row(company, action="delete", object_type="core.handbookvalue")
    assert row.object_id == str(vid)


def test_make_initial_audited_as_update(admin_client, company):
    with tenant_context(company.id):
        target = HandbookValue.objects.get(handbook__code="order_status", name="В работе")
    r = admin_client.post(f"/api/handbook-values/{target.pk}/make-initial/")
    assert r.status_code == 200
    row = last_row(
        company, action="update", object_type="core.handbookvalue", object_id=str(target.pk)
    )
    assert row.changes == {"is_initial": [False, True]}


def test_numbering_patch_audited(admin_client, company):
    r = admin_client.patch("/api/numbering/order/", {"digits": 3}, format="json")
    assert r.status_code == 200
    with tenant_context(company.id):
        rule = NumberingRule.objects.get(kind="order")
    row = last_row(company, action="update", object_type="core.numberingrule")
    assert row.object_id == str(rule.pk) and row.changes == {"digits": [5, 3]}


# --- IP ---


def test_ip_remote_addr_by_default(admin_client, company):
    admin_client.post(
        "/api/departments/",
        {"name": "A"},
        format="json",
        REMOTE_ADDR="10.1.1.1",
        HTTP_X_FORWARDED_FOR="1.2.3.4",
    )
    assert last_row(company, object_type="core.department").ip == "10.1.1.1"


def test_ip_forwarded_first_hop_when_trusted(admin_client, company, settings):
    settings.TRUST_PROXY_HEADERS = True
    admin_client.post(
        "/api/departments/",
        {"name": "A"},
        format="json",
        REMOTE_ADDR="10.1.1.1",
        HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8",
    )
    assert last_row(company, object_type="core.department").ip == "1.2.3.4"


def test_ip_garbage_forwarded_falls_back(admin_client, company, settings):
    settings.TRUST_PROXY_HEADERS = True
    admin_client.post(
        "/api/departments/",
        {"name": "A"},
        format="json",
        REMOTE_ADDR="10.1.1.1",
        HTTP_X_FORWARDED_FOR="not-an-ip",
    )
    assert last_row(company, object_type="core.department").ip == "10.1.1.1"


# --- вход ---


def test_login_writes_audit_row(company, admin_user):
    client = APIClient()
    r = client.post(
        "/api/auth/login/",
        {"login": admin_user.email, "password": "s3cret-pass"},
        format="json",
        REMOTE_ADDR="10.2.2.2",
    )
    assert r.status_code == 200
    row = last_row(company, action="login")
    assert row.user_id == admin_user.pk and row.ip == "10.2.2.2"
    assert row.object_type == "core.user" and row.object_id == str(admin_user.pk)
    assert get_current_company_id() is None
    assert "s3cret-pass" not in str(row.changes) and r.json()["access"] not in str(row.changes)


def test_failed_login_is_logged_only_for_known_user(company, admin_user):
    client = APIClient()
    for login, pwd in ((admin_user.email, "wrong"), ("ghost@audit.kz", "wrong")):
        r = client.post("/api/auth/login/", {"login": login, "password": pwd}, format="json")
        assert r.status_code == 401
    # неизвестный логин не пишется (нет компании); известный - одна запись login_failed
    assert [r.action for r in rows(company)] == ["login_failed"]
    assert AuditLog.all_objects.count() == 1


def test_switch_company_writes_login_row(make_company):
    a, admin, client = make_company()
    b, _, _ = make_company()
    Membership.objects.create(user=admin, company=b, role_id=role_id(b, "Менеджер"))
    r = client.post("/api/auth/switch-company/", {"company_id": b.id}, format="json")
    assert r.status_code == 200
    row = last_row(b, action="login")
    assert row.user_id == admin.pk and row.changes == {"switched_to": b.id}
    assert rows(a, action="login") == []
    assert get_current_company_id() is None


# --- API аудита ---


def test_audit_list_newest_first_and_shape(admin_client, company):
    admin_client.post("/api/departments/", {"name": "D1"}, format="json")
    admin_client.post("/api/departments/", {"name": "D2"}, format="json")
    r = admin_client.get("/api/audit/")
    assert r.status_code == 200
    body = r.json()
    assert {"count", "results"} <= set(body)
    ids = [x["id"] for x in body["results"]]
    assert ids == sorted(ids, reverse=True) and len(ids) >= 2
    item = body["results"][0]
    assert set(item) >= {
        "id",
        "user",
        "action",
        "object_type",
        "object_id",
        "object_repr",
        "changes",
        "ip",
        "created_at",
    }
    assert item["object_repr"] == "D2"


def test_audit_pagination(admin_client, company):
    for i in range(3):
        admin_client.post("/api/departments/", {"name": f"D{i}"}, format="json")
    r = admin_client.get("/api/audit/?page_size=2")
    body = r.json()
    assert len(body["results"]) == 2 and body["count"] >= 3 and body["next"]


def test_audit_filters(admin_client, company, admin_user):
    did = admin_client.post("/api/departments/", {"name": "F"}, format="json").json()["id"]
    admin_client.patch(f"/api/departments/{did}/", {"name": "G"}, format="json")
    other = client_with_role(company, "Менеджер")[0]
    with tenant_context(company.id):
        audit.log("restore", PlainTenant.objects.create(name="z"), other)

    def get(q):
        return admin_client.get(f"/api/audit/?{q}").json()["results"]

    assert {x["action"] for x in get("action=update")} == {"update"}
    assert {x["object_type"] for x in get("object_type=core.department")} == {"core.department"}
    only = get(f"object_type=core.department&object_id={did}")
    assert {x["object_id"] for x in only} == {str(did)} and len(only) == 2
    assert {x["user"] for x in get(f"user={other.pk}")} == {other.pk}
    assert get("action=login") == []


def test_audit_date_filters(admin_client, company, admin_user):
    with tenant_context(company.id):
        old = audit.log("create", admin_user, admin_user)
    AuditLog.all_objects.filter(pk=old.pk).update(
        created_at=datetime(2026, 5, 1, 10, 0, tzinfo=dt_tz.utc)
    )
    admin_client.post("/api/departments/", {"name": "Fresh"}, format="json")

    def ids(q):
        return {x["id"] for x in admin_client.get(f"/api/audit/?{q}").json()["results"]}

    assert old.pk in ids("created_from=2026-05-01&created_to=2026-05-01")
    assert old.pk not in ids("created_from=2026-06-01")
    assert old.pk in ids("created_to=2026-05-31")
    assert old.pk not in ids("created_from=2026-06-10T00:00:00Z")
    assert old.pk not in ids("created_to=2026-04-30")
    assert admin_client.get("/api/audit/?created_from=garbage").status_code == 400


def test_audit_read_only(admin_client, company):
    admin_client.post("/api/departments/", {"name": "R"}, format="json")
    row = last_row(company)
    for method in ("post", "put", "patch", "delete"):
        assert getattr(admin_client, method)("/api/audit/").status_code == 405
        assert getattr(admin_client, method)(f"/api/audit/{row.pk}/").status_code in (404, 405)
    assert AuditLog.all_objects.filter(pk=row.pk).exists()


def test_audit_requires_audit_view(company, admin_client):
    _, manager = client_with_role(company, "Менеджер")
    assert manager.get("/api/audit/").status_code == 403
    _, observer = client_with_role(company, "Наблюдатель")
    assert observer.get("/api/audit/").status_code == 403  # аудит - не для наблюдателя
    assert admin_client.get("/api/audit/").status_code == 200  # Администратор: audit.view


def test_audit_isolation(make_company):
    a, _, client_a = make_company()
    b, _, client_b = make_company()
    client_a.post("/api/departments/", {"name": "OnlyA"}, format="json")
    seen_b = client_b.get("/api/audit/").json()["results"]
    assert all(x["object_repr"] != "OnlyA" for x in seen_b)
    seen_a = client_a.get("/api/audit/").json()["results"]
    assert any(x["object_repr"] == "OnlyA" for x in seen_a)
    foreign_id = last_row(a).pk
    assert client_b.get(f"/api/audit/{foreign_id}/").status_code in (404, 405)


def test_audit_readonly_subscription(admin_client, company):
    expire(company)
    assert admin_client.get("/api/audit/").status_code == 200
    r = admin_client.post("/api/audit/")
    assert r.status_code == 403 and r.json()["code"] == "subscription_readonly"


# --- корзина: реестр ---


def test_register_validation(registry):
    with pytest.raises(ValueError):
        trash.register(SoftTenant, "softs", "clients.view")  # дубликат кода
    with pytest.raises(ValueError):
        trash.register(PlainTenant, "plain", "clients.view")  # не SoftDeleteModel
    with pytest.raises(ValueError):
        trash.register(SoftTenant, "other", "nonsense.view")  # неизвестное право


# --- корзина: список ---


def test_trash_lists_deleted_newest_first(admin_client, company, registry):
    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=dt_tz.utc)
    with time_machine.travel(t0, tick=False):
        first = make_soft(company, "first", deleted=True)
    with time_machine.travel(t0 + timedelta(hours=1), tick=False):
        second = make_soft(company, "second", deleted=True)
    make_soft(company, "alive")
    r = admin_client.get("/api/trash/")
    assert r.status_code == 200
    results = r.json()["results"]
    assert [x["id"] for x in results] == [second.pk, first.pk]
    assert results[0]["code"] == "softs" and results[0]["label"] == "second"
    assert results[0]["deleted_at"]
    assert r.json()["count"] == 2


def test_trash_code_filter_and_pagination(admin_client, company, registry):
    for i in range(3):
        make_soft(company, f"s{i}", deleted=True)
    assert len(admin_client.get("/api/trash/?code=softs").json()["results"]) == 3
    assert admin_client.get("/api/trash/?code=nope").json()["results"] == []
    page = admin_client.get("/api/trash/?page_size=2").json()
    assert len(page["results"]) == 2 and page["count"] == 3 and page["next"]


def test_trash_needs_trash_view_and_type_permission(company, registry):
    make_soft(company, "gone", deleted=True)
    _, manager = client_with_role(company, "Менеджер")  # trash.view + clients.view
    assert len(manager.get("/api/trash/").json()["results"]) == 1
    _, mechanic = client_with_role(company, "Механик")  # без trash.view
    assert mechanic.get("/api/trash/").status_code == 403
    trash.register(SoftTenant, "fin", "finance.update")  # Менеджер не имеет finance.update
    assert {x["code"] for x in manager.get("/api/trash/").json()["results"]} == {"softs"}


def test_trash_hides_types_without_permission(company, registry):
    make_soft(company, "gone", deleted=True)
    trash.clear_registry()
    trash.register(SoftTenant, "softs", "finance.update")
    _, manager = client_with_role(company, "Менеджер")
    assert manager.get("/api/trash/").json()["results"] == []


def test_trash_isolation(make_company, registry):
    a, _, client_a = make_company()
    b, _, client_b = make_company()
    obj = make_soft(a, "secret-a", deleted=True)
    assert client_b.get("/api/trash/").json()["results"] == []
    assert client_b.post(f"/api/trash/softs/{obj.pk}/restore/").status_code == 404
    with tenant_context(a.id):
        assert SoftTenant.trash.filter(pk=obj.pk).exists()
    assert client_a.get("/api/trash/").json()["count"] == 1


# --- корзина: восстановление ---


def test_restore_restores_and_audits(admin_client, company, admin_user, registry):
    obj = make_soft(company, "back", deleted=True)
    r = admin_client.post(f"/api/trash/softs/{obj.pk}/restore/")
    assert r.status_code == 200
    with tenant_context(company.id):
        assert SoftTenant.objects.filter(pk=obj.pk).exists()
    row = last_row(company, action="restore")
    assert row.object_type == "core_tests.softtenant" and row.object_id == str(obj.pk)
    assert row.user_id == admin_user.pk and row.object_repr == "back"
    assert admin_client.get("/api/trash/").json()["results"] == []


def test_restore_404_cases(admin_client, company, registry):
    alive = make_soft(company, "alive")
    assert admin_client.post(f"/api/trash/softs/{alive.pk}/restore/").status_code == 404
    assert admin_client.post("/api/trash/softs/999999/restore/").status_code == 404
    assert admin_client.post("/api/trash/softs/abc/restore/").status_code == 404
    gone = make_soft(company, "g", deleted=True)
    assert admin_client.post(f"/api/trash/unknown/{gone.pk}/restore/").status_code == 404
    assert rows(company, action="restore") == []


def test_restore_permissions(company, registry):
    obj = make_soft(company, "gone", deleted=True)
    _, manager = client_with_role(company, "Менеджер")  # trash.view, но не trash.update
    assert manager.post(f"/api/trash/softs/{obj.pk}/restore/").status_code == 403
    _, observer = client_with_role(company, "Наблюдатель")
    assert observer.post(f"/api/trash/softs/{obj.pk}/restore/").status_code == 403
    # trash.update есть, права типа нет
    with tenant_context(company.id):
        role = Role.objects.create(name="Восст", permissions=["trash.view", "trash.update"])
    user = User.objects.create_user(email="rest@audit.kz", password=PASSWORD)
    Membership.objects.create(user=user, company=company, role=role)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert c.post(f"/api/trash/softs/{obj.pk}/restore/").status_code == 403
    with tenant_context(company.id):
        assert SoftTenant.trash.filter(pk=obj.pk).exists()


def test_trash_readonly_subscription(admin_client, company, registry):
    obj = make_soft(company, "gone", deleted=True)
    expire(company)
    assert admin_client.get("/api/trash/").status_code == 200
    r = admin_client.post(f"/api/trash/softs/{obj.pk}/restore/")
    assert r.status_code == 403 and r.json()["code"] == "subscription_readonly"
    with tenant_context(company.id):
        assert SoftTenant.trash.filter(pk=obj.pk).exists()


# --- queryset.restore ---


def test_queryset_restore(company):
    a = make_soft(company, "a", deleted=True)
    b = make_soft(company, "b", deleted=True)
    make_soft(company, "c", deleted=True)
    with tenant_context(company.id):
        assert SoftTenant.trash.filter(pk__in=[a.pk, b.pk]).restore() == 2
        assert sorted(SoftTenant.objects.values_list("name", flat=True)) == ["a", "b"]
        assert SoftTenant.trash.count() == 1
        assert SoftTenant.trash.filter(name="none").restore() == 0


# --- fix round 1 ---


@pytest.mark.parametrize(
    "query",
    [
        "created_to=2026-13-45",
        "created_from=2026-02-30T10:00:00",
        "created_to=9999-12-31",
        "created_from=garbage",
    ],
)
def test_audit_bad_date_filters_are_400(admin_client, query):
    r = admin_client.get(f"/api/audit/?{query}")
    assert r.status_code == 400
    assert query.split("=")[0] in r.json()


def test_auditlog_cannot_be_overwritten_by_pk(company, admin_user):
    from django.db import IntegrityError, transaction

    with tenant_context(company.id):
        row = audit.log("create", admin_user, admin_user, {"a": 1})
        clone = AuditLog(
            pk=row.pk, company_id=company.id, action="update", object_type="x", object_id="1"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            clone.save()
        with pytest.raises(AuditLogImmutable):
            AuditLog(company_id=company.id, action="create", object_type="x", object_id="1").save(
                update_fields=["action"]
            )
        stored = AuditLog.objects.get(pk=row.pk)
    assert (stored.action, stored.object_type, stored.changes) == ("create", "core.user", {"a": 1})


def test_make_initial_logs_previous_initial_losing_flag(admin_client, company):
    with tenant_context(company.id):
        old = HandbookValue.objects.get(handbook__code="order_status", is_initial=True)
        target = HandbookValue.objects.get(handbook__code="order_status", name="В работе")
    assert admin_client.post(f"/api/handbook-values/{target.pk}/make-initial/").status_code == 200
    lost = last_row(company, action="update", object_id=str(old.pk))
    assert lost.object_type == "core.handbookvalue"
    assert lost.changes == {"is_initial": [True, False]}


def test_noop_patch_writes_no_update_row(admin_client, company):
    did = admin_client.post("/api/departments/", {"name": "Same"}, format="json").json()["id"]
    admin_client.patch(f"/api/departments/{did}/", {"name": "Same"}, format="json")
    assert rows(company, action="update", object_type="core.department") == []


def test_masking_depth_limit_is_one_nested_level(company, admin_user):
    with tenant_context(company.id):
        row = audit.log(
            "update", admin_user, admin_user, {"a": {"token": "x", "b": {"token": "deep"}}}
        )
    assert row.changes["a"]["token"] == "***"
    assert row.changes["a"]["b"] == {"token": "deep"}  # глубже одного уровня не маскируется
