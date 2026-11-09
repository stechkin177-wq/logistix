from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core.api.auth import PasswordChangeThrottle
from apps.core.audit.models import AuditLog
from apps.core.models import User
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db

URL = "/api/auth/password/"
NEW = "Brand-new-passphrase-42"


@pytest.fixture(autouse=True)
def _clean_throttle():
    cache.clear()
    yield
    cache.clear()


def change(client, old=TEST_PASSWORD, new=NEW):
    return client.post(URL, {"old_password": old, "new_password": new}, format="json")


def login(login_value, password):
    return APIClient().post(
        "/api/auth/login/", {"login": login_value, "password": password}, format="json"
    )


def test_unauthenticated_is_401(api_client):
    assert change(api_client).status_code == 401


def test_wrong_old_password(admin_client, admin_user):
    r = change(admin_client, old="not-my-password")
    assert r.status_code == 400 and "old_password" in r.data
    admin_user.refresh_from_db()
    assert admin_user.check_password(TEST_PASSWORD)


@pytest.mark.parametrize("weak", ["short", "12345678", "password", "EMAIL"])
def test_weak_new_password(admin_client, admin_user, weak):
    r = change(admin_client, new=admin_user.email if weak == "EMAIL" else weak)
    assert r.status_code == 400 and "new_password" in r.data
    admin_user.refresh_from_db()
    assert admin_user.check_password(TEST_PASSWORD)


def test_same_password_rejected(admin_client):
    r = change(admin_client, new=TEST_PASSWORD)
    assert r.status_code == 400 and "new_password" in r.data


def test_missing_fields(admin_client):
    r = admin_client.post(URL, {}, format="json")
    assert r.status_code == 400 and {"old_password", "new_password"} <= set(r.data)


def test_success_switches_password(admin_client, admin_user):
    r = change(admin_client)
    assert r.status_code == 200 and {"access", "refresh"} <= set(r.json())
    assert login(admin_user.email, TEST_PASSWORD).status_code == 401
    assert login(admin_user.email, NEW).status_code == 200


def test_success_audit_is_masked(admin_client, admin_user):
    assert change(admin_client).status_code == 200
    row = AuditLog.all_objects.filter(object_type="core.user", action="update").latest("id")
    assert row.changes == {"password": "***"} and row.user_id == admin_user.pk
    dump = " ".join(str(a.changes) + a.object_repr for a in AuditLog.all_objects.all())
    assert NEW not in dump and TEST_PASSWORD not in dump


def test_readonly_subscription_blocks(admin_client, admin_user, company):
    Subscription.objects.filter(company=company).update(
        ends_at=datetime.now(UTC) - timedelta(days=20)
    )
    r = change(admin_client)
    assert r.status_code == 403 and r.json()["code"] == "subscription_readonly"
    admin_user.refresh_from_db()
    assert admin_user.check_password(TEST_PASSWORD)


def test_throttled(admin_client, admin_user, monkeypatch):
    monkeypatch.setattr(PasswordChangeThrottle, "THROTTLE_RATES", {"password_change": "3/min"})
    codes = [change(admin_client, old=f"wrong-{i}").status_code for i in range(5)]
    assert codes == [400, 400, 400, 429, 429]
    assert User.objects.get(pk=admin_user.pk).check_password(TEST_PASSWORD)


@pytest.mark.parametrize("weak", ["12345678", "password", "qwerty123", "1234567890123"])
def test_production_validators_reject_weak_passwords(weak):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_password(weak)


def test_validators_configured_in_settings():
    from django.conf import settings

    names = {v["NAME"].rsplit(".", 1)[1] for v in settings.AUTH_PASSWORD_VALIDATORS}
    assert names == {
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    }
