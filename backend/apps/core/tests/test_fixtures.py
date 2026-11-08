import pytest

from apps.billing.models import Subscription
from apps.core.models import Role

pytestmark = pytest.mark.django_db


def test_company_fixture_is_complete(company, admin_user):
    assert Role.all_objects.filter(company=company).count() == 7
    assert Subscription.objects.filter(company=company).exists()
    assert admin_user.memberships.get().company_id == company.id


def test_admin_client_is_authenticated(admin_client):
    assert admin_client.get("/api/roles/").status_code == 200


def test_make_company_gives_independent_triples(make_company):
    a, _, client_a = make_company("A")
    b, _, _ = make_company("B", modules=["forwarding", "fleet"])
    assert a.id != b.id
    assert b.modules == ["forwarding", "fleet", "logistics", "finance", "documents"]
    assert len(client_a.get("/api/roles/").json()) == 7
