import threading

import pytest
from django.db import IntegrityError, transaction

from apps.core.models import Company, LegalEntity
from apps.core.tenancy import (
    NoTenantContext,
    TenantMismatch,
    get_current_company_id,
    reset_current_company,
    set_current_company,
    tenant_context,
)

from .models import PlainTenant, SoftOnly, SoftTenant

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_tenant():
    set_current_company(None)
    yield
    set_current_company(None)


@pytest.fixture
def company_a():
    return Company.objects.create(name="A")


@pytest.fixture
def company_b():
    return Company.objects.create(name="B")


def test_company_defaults():
    c = Company.objects.create(name="X")
    assert c.modules == ["forwarding"]


def test_context_roundtrip(company_a):
    assert get_current_company_id() is None
    set_current_company(company_a.id)
    assert get_current_company_id() == company_a.id


def test_save_sets_company_from_context(company_a):
    set_current_company(company_a.id)
    obj = PlainTenant.objects.create(name="o")
    assert obj.company_id == company_a.id


def test_save_without_context_fails_closed():
    with pytest.raises(NoTenantContext):
        PlainTenant(name="o").save()


def test_isolation_between_companies(company_a, company_b):
    set_current_company(company_a.id)
    PlainTenant.objects.create(name="a")
    set_current_company(company_b.id)
    PlainTenant.objects.create(name="b")
    assert [o.name for o in PlainTenant.objects.all()] == ["b"]
    set_current_company(company_a.id)
    assert [o.name for o in PlainTenant.objects.all()] == ["a"]
    assert PlainTenant.all_objects.count() == 2


@pytest.mark.parametrize("model", [PlainTenant, SoftTenant])
def test_no_context_raises(model):
    with pytest.raises(NoTenantContext):
        model.objects.all()
    with pytest.raises(NoTenantContext):
        list(model.objects.filter(name="x"))


def test_trash_without_context_raises():
    with pytest.raises(NoTenantContext):
        SoftTenant.trash.all()


def test_soft_delete_and_restore_tenant(company_a):
    set_current_company(company_a.id)
    obj = SoftTenant.objects.create(name="s")
    obj.delete()
    assert obj.deleted_at is not None
    assert SoftTenant.objects.count() == 0
    assert [o.pk for o in SoftTenant.trash.all()] == [obj.pk]
    assert SoftTenant.all_objects.count() == 1
    obj.restore()
    assert obj.deleted_at is None
    assert SoftTenant.objects.count() == 1
    assert SoftTenant.trash.count() == 0


def test_soft_tenant_combined_isolation(company_a, company_b):
    set_current_company(company_a.id)
    SoftTenant.objects.create(name="a-live")
    SoftTenant.objects.create(name="a-dead").delete()
    set_current_company(company_b.id)
    SoftTenant.objects.create(name="b-live")
    SoftTenant.objects.create(name="b-dead").delete()
    assert [o.name for o in SoftTenant.objects.all()] == ["b-live"]
    assert [o.name for o in SoftTenant.trash.all()] == ["b-dead"]
    assert SoftTenant.all_objects.count() == 4


def test_soft_delete_without_tenant():
    obj = SoftOnly.objects.create(name="s")
    obj.delete()
    assert SoftOnly.objects.count() == 0
    assert SoftOnly.trash.count() == 1
    obj.restore()
    assert SoftOnly.objects.count() == 1


def test_legal_entity_is_tenant_scoped(company_a, company_b):
    set_current_company(company_a.id)
    LegalEntity.objects.create(name="ТОО А", bin="123456789012", is_default=True)
    set_current_company(company_b.id)
    assert LegalEntity.objects.count() == 0
    assert LegalEntity.all_objects.count() == 1


def test_set_returns_token_and_reset_restores(company_a, company_b):
    t1 = set_current_company(company_a.id)
    t2 = set_current_company(company_b.id)
    reset_current_company(t2)
    assert get_current_company_id() == company_a.id
    reset_current_company(t1)
    assert get_current_company_id() is None


def test_tenant_context_does_not_survive(company_a):
    with tenant_context(company_a.id):
        assert get_current_company_id() == company_a.id
    assert get_current_company_id() is None


def test_tenant_context_nested_restores_outer(company_a, company_b):
    with tenant_context(company_a.id):
        with tenant_context(company_b.id):
            assert get_current_company_id() == company_b.id
        assert get_current_company_id() == company_a.id


def test_tenant_context_resets_after_exception(company_a):
    with pytest.raises(ValueError):
        with tenant_context(company_a.id):
            raise ValueError
    assert get_current_company_id() is None


def test_threads_see_only_own_company(company_a, company_b):
    barrier = threading.Barrier(2)
    seen = {}

    def work(key, cid):
        with tenant_context(cid):
            barrier.wait(timeout=5)
            seen[key] = get_current_company_id()
            barrier.wait(timeout=5)
        seen[key + "_after"] = get_current_company_id()

    threads = [
        threading.Thread(target=work, args=("a", company_a.id)),
        threading.Thread(target=work, args=("b", company_b.id)),
    ]
    with tenant_context(None):
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert seen == {"a": company_a.id, "b": company_b.id, "a_after": None, "b_after": None}


def test_queryset_delete_is_soft(company_a):
    with tenant_context(company_a.id):
        for n in "xyz":
            SoftTenant.objects.create(name=n)
        assert SoftTenant.objects.filter(name__in=["x", "y"]).delete() == 2
        assert SoftTenant.objects.count() == 1
        assert SoftTenant.trash.count() == 2
        assert SoftTenant.all_objects.count() == 3


def test_all_objects_and_trash_delete_are_soft(company_a):
    with tenant_context(company_a.id):
        SoftTenant.objects.create(name="x")
        SoftTenant.all_objects.all().delete()
        assert SoftTenant.trash.count() == 1


def test_queryset_delete_soft_only_model():
    SoftOnly.objects.create(name="x")
    SoftOnly.objects.all().delete()
    assert SoftOnly.trash.count() == 1


def test_hard_delete_queryset_and_instance(company_a):
    with tenant_context(company_a.id):
        SoftTenant.objects.create(name="x")
        SoftTenant.objects.create(name="y")
        SoftTenant.objects.filter(name="x").hard_delete()
        assert SoftTenant.all_objects.count() == 1
        SoftTenant.objects.get(name="y").hard_delete()
        assert SoftTenant.all_objects.count() == 0


def test_plain_tenant_queryset_delete_is_hard(company_a):
    with tenant_context(company_a.id):
        PlainTenant.objects.create(name="x")
        PlainTenant.objects.all().delete()
        assert PlainTenant.all_objects.count() == 0


def test_explicit_other_company_with_context_raises(company_a, company_b):
    with tenant_context(company_a.id):
        with pytest.raises(TenantMismatch):
            PlainTenant(name="x", company_id=company_b.id).save()
        PlainTenant(name="ok", company_id=company_a.id).save()


def test_explicit_company_without_context_allowed(company_b):
    obj = PlainTenant(name="x", company_id=company_b.id)
    obj.save()
    assert PlainTenant.all_objects.get(pk=obj.pk).company_id == company_b.id


def test_bulk_create_without_company_fails_safe(company_a):
    with tenant_context(company_a.id):
        with pytest.raises(IntegrityError), transaction.atomic():
            PlainTenant.objects.bulk_create([PlainTenant(name="x")])
