"""Мобильная версия водителя: «я», свои рейсы, действия, изоляция, выдача и отзыв доступа."""

import itertools

import pytest
from rest_framework.test import APIClient

from apps.billing.models import Plan
from apps.core.api.auth import issue_tokens
from apps.core.models import Membership, Role, User
from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.drivers.models import Driver
from apps.forwarding.tests.test_trips import make_cargos, new_trip

pytestmark = pytest.mark.django_db

ME = "/api/driver/me/"
TRIPS = "/api/driver/trips/"
PASSWORD = "Drv-pass-2026!x"
_n = itertools.count(1)


def app_company(make_company, name="Mobile"):
    plan = Plan.objects.get(code="start")
    mods = list(plan.modules)
    for code in ("drivers", "logistics", "driver_app"):
        if code not in mods:
            mods.append(code)
    Plan.objects.filter(code="start").update(modules=mods)
    company, admin, api = make_company(name, modules=["logistics"])
    set_company_modules(company, ["logistics", "drivers", "driver_app"])
    return company, admin, api


def driver_with_login(company, name="Иванов Иван", phone="+77001112233"):
    """Водитель с аккаунтом и ролью «Водитель»: (Driver, клиент водителя)."""
    user = User.objects.create_user(phone=phone, password=PASSWORD, full_name=name)
    with tenant_context(company.id):
        role = Role.objects.get(name="Водитель")
        driver = Driver.objects.create(full_name=name, phone=phone, user=user)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return driver, api


@pytest.fixture
def mob(make_company):
    company, admin, api = app_company(make_company)
    driver, drv_api = driver_with_login(company)
    return company, api, driver, drv_api


def trip_for(api, company, driver, **extra):
    _, ids = make_cargos(company, 1)
    return new_trip(api, ids, driver=driver.pk, **extra)


def test_me_and_unlinked_user(mob, make_company):
    company, admin_api, driver, drv_api = mob
    r = drv_api.get(ME)
    assert r.status_code == 200 and r.json()["driver"]["full_name"] == "Иванов Иван"
    assert admin_api.get(ME).status_code == 403  # у администратора нет карточки водителя


def test_role_without_permission_and_module_off(mob):
    company, admin_api, driver, drv_api = mob
    manager = User.objects.create_user(email="m@m.kz", password=PASSWORD)
    with tenant_context(company.id):
        role = Role.objects.get(name="Менеджер")
        Driver.objects.filter(pk=driver.pk).update(user=manager)
    Membership.objects.create(user=manager, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(manager, company.id)['access']}")
    assert api.get(ME).status_code == 403  # права driver.use нет
    set_company_modules(company, ["logistics", "drivers"])
    assert drv_api.get(ME).status_code == 403  # модуль выключен


def test_trip_lifecycle_and_scopes(mob):
    company, admin_api, driver, drv_api = mob
    trip = trip_for(admin_api, company, driver)
    assert drv_api.get(f"{TRIPS}?scope=current").json()["results"] == []
    upcoming = drv_api.get(f"{TRIPS}?scope=upcoming").json()["results"]
    assert [t["id"] for t in upcoming] == [trip["id"]] and upcoming[0]["actions"] == ["start"]
    url = f"{TRIPS}{trip['id']}/action/"
    bad = drv_api.post(url, {"action": "complete"}, format="json")
    assert bad.status_code == 400  # до выезда завершить нельзя
    started = drv_api.post(url, {"action": "start"}, format="json")
    assert started.status_code == 200 and started.json()["status"]["code"] == "IN_PROGRESS"
    assert started.json()["actions"] == ["unloading", "complete"]
    assert [t["id"] for t in drv_api.get(f"{TRIPS}?scope=current").json()["results"]] == [
        trip["id"]
    ]
    assert (
        drv_api.post(url, {"action": "unloading", "vehicle_km": 5}, format="json").status_code
        == 400
    )
    assert drv_api.post(url, {"action": "unloading"}, format="json").status_code == 200
    done = drv_api.post(url, {"action": "complete"}, format="json")
    assert done.status_code == 200 and done.json()["status"]["code"] == "COMPLETED"
    assert done.json()["actions"] == []
    history = drv_api.get(f"{TRIPS}?scope=history").json()["results"]
    assert [t["id"] for t in history] == [trip["id"]]
    assert drv_api.get(f"{TRIPS}?scope=zzz").status_code == 400


def test_detail_has_stops_and_hides_prices(mob):
    company, admin_api, driver, drv_api = mob
    trip = trip_for(admin_api, company, driver)
    body = drv_api.get(f"{TRIPS}{trip['id']}/").json()
    assert body["consignments"][0]["name"] == "Груз 0" and isinstance(body["stops"], list)
    text = str(body).lower()
    assert "price" not in text and "carrier" not in text


def test_other_drivers_trip_is_404(mob):
    company, admin_api, driver, drv_api = mob
    other, _ = driver_with_login(company, "Петров", "+77002223344")
    theirs = trip_for(admin_api, company, other)
    assert drv_api.get(f"{TRIPS}{theirs['id']}/").status_code == 404
    assert (
        drv_api.post(
            f"{TRIPS}{theirs['id']}/action/", {"action": "start"}, format="json"
        ).status_code
        == 404
    )
    assert drv_api.get(f"{TRIPS}?scope=upcoming").json()["results"] == []


def test_grant_login_and_revoke_access(make_company):
    company, admin, api = app_company(make_company, "Grant")
    with tenant_context(company.id):
        driver = Driver.objects.create(full_name="Сидоров", phone="8 700 333 44 55")
        no_phone = Driver.objects.create(full_name="Без телефона")
    url = f"/api/drivers/{driver.pk}/grant-access/"
    assert api.post(url, {}, format="json").status_code == 400  # пароль обязателен
    assert api.post(url, {"password": "123"}, format="json").status_code == 400  # слабый
    assert (
        api.post(
            f"/api/drivers/{no_phone.pk}/grant-access/", {"password": PASSWORD}, format="json"
        ).status_code
        == 400
    )
    ok = api.post(url, {"password": PASSWORD}, format="json")
    assert ok.status_code == 201 and ok.json()["login"] == "+77003334455"
    assert api.post(url, {"password": PASSWORD}, format="json").status_code == 400  # уже выдан
    with tenant_context(company.id):
        driver.refresh_from_db()
        assert driver.user_id is not None
    login = APIClient().post(
        "/api/auth/login/", {"login": "8 700 333 44 55", "password": PASSWORD}, format="json"
    )
    assert login.status_code == 200
    drv = APIClient()
    drv.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
    assert drv.get(ME).status_code == 200
    assert (
        api.post(f"/api/drivers/{driver.pk}/revoke-access/", {}, format="json").status_code == 200
    )
    with tenant_context(company.id):
        driver.refresh_from_db()
        assert driver.user_id is None
    assert drv.get(ME).status_code in (401, 403)


def test_grant_requires_update_permission(make_company):
    company, admin, api = app_company(make_company, "Perm")
    with tenant_context(company.id):
        driver = Driver.objects.create(full_name="Т", phone="+77004445566")
        role = Role.objects.get(name="Наблюдатель")
    viewer = User.objects.create_user(email="v@v.kz", password=PASSWORD)
    Membership.objects.create(user=viewer, company=company, role=role)
    vapi = APIClient()
    vapi.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(viewer, company.id)['access']}")
    r = vapi.post(f"/api/drivers/{driver.pk}/grant-access/", {"password": PASSWORD}, format="json")
    assert r.status_code == 403
