"""Неактивный клиент: новые заказы запрещены, существующие заказы и рейсы работают."""

import pytest
from rest_framework.exceptions import ValidationError

from apps.core.tenancy import tenant_context
from apps.forwarding.models import Client, Order
from apps.forwarding.orders.services import create_order
from apps.forwarding.tests.test_orders import ORDERS, make_client, make_order, new_order

pytestmark = pytest.mark.django_db


def deactivate(company, client):
    with tenant_context(company.id):
        Client.objects.filter(pk=client.pk).update(status=Client.INACTIVE)


def test_create_order_for_inactive_client_is_rejected_with_message(admin_client, company):
    client = make_client(company)
    deactivate(company, client)
    r = admin_client.post(ORDERS, {"client": client.pk}, format="json")
    assert r.status_code == 400
    assert "неактивен" in str(r.json()["client"])
    with tenant_context(company.id):
        assert Order.objects.count() == 0


def test_service_level_guard_rejects_inactive_client(company, admin_user):
    client = make_client(company)
    deactivate(company, client)
    with tenant_context(company.id), pytest.raises(ValidationError):
        create_order({"client": Client.objects.get(pk=client.pk)}, admin_user)


def test_active_client_still_works(admin_client, company):
    client = make_client(company)
    new_order(admin_client, client)


def test_existing_order_of_inactive_client_keeps_working(admin_client, company):
    client = make_client(company)
    order = make_order(company, client)
    deactivate(company, client)
    r = admin_client.patch(f"{ORDERS}{order.pk}/", {"client_rate": "1000.00"}, format="json")
    assert r.status_code == 200, r.content
    assert admin_client.get(f"{ORDERS}{order.pk}/").status_code == 200


def test_moving_order_to_inactive_client_is_rejected_but_to_active_is_fine(admin_client, company):
    old = make_client(company, "Старый")
    inactive = make_client(company, "Неактивный")
    other = make_client(company, "Другой")
    order = make_order(company, old)
    deactivate(company, inactive)
    bad = admin_client.patch(f"{ORDERS}{order.pk}/", {"client": inactive.pk}, format="json")
    assert bad.status_code == 400 and "неактивен" in str(bad.json()["client"])
    ok = admin_client.patch(f"{ORDERS}{order.pk}/", {"client": other.pk}, format="json")
    assert ok.status_code == 200


def test_same_inactive_client_in_patch_is_not_a_change(admin_client, company):
    client = make_client(company)
    order = make_order(company, client)
    deactivate(company, client)
    body = {"client": client.pk, "comment": "ok"}
    r = admin_client.patch(f"{ORDERS}{order.pk}/", body, format="json")
    assert r.status_code == 200
