import pytest

from apps.core.models import Company, LegalEntity
from apps.core.tenancy import NoTenantContext, get_current_company_id, set_current_company

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
