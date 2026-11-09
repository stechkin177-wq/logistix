"""Восстановление из корзины проверяется по лимитам тарифа (нельзя обойти «удалить и вернуть»)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import limits, plans
from apps.core.tenancy import tenant_context
from apps.drivers.models import Driver
from apps.fleet.models import Vehicle
from apps.forwarding.models import Carrier, Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def co(make_company):
    company, _, api = make_company("Rest", modules=["logistics", "fleet", "drivers"])
    plan = company.subscription.plan
    plans.update_plan(plan, modules=list({*plan.modules, "fleet", "drivers"}))
    return company, api


def set_limit(company, **values):
    plan = company.subscription.plan
    plans.update_plan(plan, limits={**plan.limits, **values})


def trash_restore(api, code, pk):
    return api.post(f"/api/trash/{code}/{pk}/restore/")


@pytest.mark.parametrize(
    ("make", "code", "limit_code"),
    [
        (lambda: Vehicle.objects.create(plate="R1"), "vehicles", "max_vehicles"),
        (lambda: Driver.objects.create(full_name="Р"), "drivers", "max_drivers"),
        (lambda: Client.objects.create(name="Р"), "clients", "max_clients"),
        (lambda: Carrier.objects.create(name="Р"), "carriers", "max_carriers"),
    ],
)
def test_restore_is_blocked_over_limit_and_allowed_after_upgrade(co, make, code, limit_code):
    company, api = co
    set_limit(company, **{limit_code: 1})
    with tenant_context(company.id):
        first = make()
        first.delete()  # в корзину: место освободилось
        # создаём второй такой же объект вместо удалённого, занимая весь лимит
        model = type(first)
        other = model.objects.create(**_unique(first))
    r = trash_restore(api, code, first.pk)
    assert r.status_code == 402, r.content
    body = r.json()
    assert body["code"] == "limit_exceeded" and body["limit_code"] == limit_code
    assert body["action"] == "restore" and "Восстановление невозможно" in body["detail"]
    assert (body["limit"], body["usage"]) == (1, 1)
    with tenant_context(company.id):
        assert model.trash.filter(pk=first.pk).exists()  # остался в корзине, ничего не потеряно
    assert api.get("/api/trash/").status_code == 200  # просмотр корзины доступен
    set_limit(company, **{limit_code: 2})  # повышение тарифа
    assert trash_restore(api, code, first.pk).status_code == 200
    with tenant_context(company.id):
        assert model.objects.filter(pk__in=[first.pk, other.pk]).count() == 2


def _unique(obj):
    """Поля второго объекта той же модели с другим уникальным значением."""
    if isinstance(obj, Vehicle):
        return {"plate": "R2"}
    if isinstance(obj, Driver):
        return {"full_name": "Р2"}
    return {"name": "Р2"}


def test_restore_without_limit_or_below_it_is_allowed(co):
    company, api = co
    with tenant_context(company.id):
        v = Vehicle.objects.create(plate="F1")
        v.delete()
    assert trash_restore(api, "vehicles", v.pk).status_code == 200  # лимита нет
    set_limit(company, max_vehicles=1)
    with tenant_context(company.id):
        v.delete()
    assert trash_restore(api, "vehicles", v.pk).status_code == 200  # место есть


def test_zero_limit_blocks_restore_and_downgrade_does_not_lose_trash(co):
    company, api = co
    with tenant_context(company.id):
        v = Vehicle.objects.create(plate="Z1")
        v.delete()
    set_limit(company, max_vehicles=0)
    assert trash_restore(api, "vehicles", v.pk).status_code == 402
    with tenant_context(company.id):
        assert Vehicle.trash.filter(pk=v.pk).exists()


def test_monthly_limit_counts_restored_object_only_if_created_this_month(co):
    from apps.billing.limits import _month_start
    from apps.forwarding.models import Order

    company, api = co
    start = _month_start(company.id)
    assert limits.BY_CODE["max_orders_per_month"]["scope"] == "month"

    class Fake:  # объект прошлого месяца не занимает лимит текущего
        company_id = company.id
        created_at = start - timedelta(days=3)
        _meta = Order._meta

    set_limit(company, max_orders_per_month=0)
    limits.check_restore(Fake())  # не бросает: месяц другой
    Fake.created_at = timezone.now()
    with pytest.raises(Exception) as e:  # создан в текущем месяце: лимит 0 блокирует
        limits.check_restore(Fake())
    assert getattr(e.value, "status_code", None) == 402


def test_model_level_restore_checks_limits_too(co):
    """Проверка не только в API корзины: любой вызов restore() объекта."""
    company, _ = co
    set_limit(company, max_clients=1)
    with tenant_context(company.id):
        a = Client.objects.create(name="A")
        a.delete()
        Client.objects.create(name="B")
        with pytest.raises(Exception) as e:
            a.restore()
        assert getattr(e.value, "status_code", None) == 402
        assert Client.trash.filter(pk=a.pk).exists()
