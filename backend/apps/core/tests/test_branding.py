"""Оформление компании: GET/PATCH /api/company/branding/ и публичный GET /api/branding/."""

import itertools
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core import rls
from apps.core.api.auth import issue_tokens
from apps.core.api.branding import BrandingThrottle
from apps.core.audit.models import AuditLog
from apps.core.branding import PLATFORM_DEFAULTS
from apps.core.models import CompanyBranding, Membership, Role, TenantModel, User
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

URL = "/api/company/branding/"
PUBLIC = "/api/branding/"
_n = itertools.count(1)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture(autouse=True)
def _clean_throttle():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


def api_with_role(company, role_name):
    user = User.objects.create_user(email=f"br{next(_n)}@x.kz", password="pw-pw-pw-1")
    with tenant_context(company.id):
        role = Role.objects.get(name=role_name)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return api


def upload(api, name, content, **extra):
    return api.patch(URL, {"logo": SimpleUploadedFile(name, content), **extra}, format="multipart")


def stored(company):
    return CompanyBranding.objects.filter(company=company).first()


def disk(path):
    return (Path(settings.MEDIA_ROOT) / path).exists()


# --- чтение и правка ---

DEFAULT_OWN = {"app_name": "", "logo_url": None, "primary_color": "#2563EB", "theme": "system"}


def test_get_defaults_without_creating_row(admin_client, company):
    r = admin_client.get(URL)
    assert r.status_code == 200 and r.data == DEFAULT_OWN
    assert stored(company) is None  # чтение ничего не пишет


def test_patch_saves_and_does_not_touch_other_company(two):
    (a, _, api_a), (b, _, api_b) = two
    r = api_a.patch(
        URL,
        {"app_name": "  Моя Логистика ", "primary_color": "#aabbcc", "theme": "dark"},
        format="json",
    )
    assert r.status_code == 200, r.content
    expected = {**DEFAULT_OWN, "app_name": "Моя Логистика", "primary_color": "#AABBCC"}
    assert r.data == {**expected, "theme": "dark"}
    assert api_a.get(URL).data == r.data
    row = stored(a)
    assert (row.app_name, row.primary_color, row.theme) == ("Моя Логистика", "#AABBCC", "dark")
    assert api_b.get(URL).data == DEFAULT_OWN
    assert stored(b) is None
    r = api_b.patch(URL, {"primary_color": "#000000"}, format="json")
    assert r.status_code == 200 and stored(a).primary_color == "#AABBCC"
    assert api_a.get(URL).data["primary_color"] == "#AABBCC"
    assert stored(a).pk != stored(b).pk


def test_patch_is_partial(admin_client, company):
    admin_client.patch(URL, {"app_name": "Имя", "theme": "light"}, format="json")
    r = admin_client.patch(URL, {"primary_color": "#112233"}, format="json")
    assert r.data["app_name"] == "Имя" and r.data["theme"] == "light"


@pytest.mark.parametrize(
    "payload",
    [
        {"primary_color": "red"},
        {"primary_color": "#12345"},
        {"primary_color": "#GGGGGG"},
        {"primary_color": "2563EB"},
        {"primary_color": "#2563EB00"},
        {"theme": "blue"},
        {"theme": ""},
        {"app_name": "x" * 65},
    ],
)
def test_validation(admin_client, payload):
    r = admin_client.patch(URL, payload, format="json")
    assert r.status_code == 400 and set(r.data) == set(payload), r.content


@pytest.mark.parametrize(
    "field",
    ["custom_domain", "company", "id", "logo_url", "anything"],
)
def test_forbidden_and_unknown_fields_are_400(admin_client, company, field):
    r = admin_client.patch(URL, {field: "evil.example.com"}, format="json")
    assert r.status_code == 400 and field in r.data
    assert stored(company) is None or stored(company).custom_domain is None


def test_custom_domain_is_not_editable_even_with_valid_fields(admin_client, company):
    r = admin_client.patch(URL, {"theme": "dark", "custom_domain": "x.kz"}, format="json")
    assert r.status_code == 400
    assert stored(company) is None or stored(company).theme == "system"  # ничего не применено


def test_plan_without_white_label_can_still_brand(admin_client, company):
    sub = Subscription.objects.get(company=company)
    sub.plan.options = {"white_label": False, "custom_domain": False}
    sub.plan.save()
    assert admin_client.patch(URL, {"theme": "dark"}, format="json").status_code == 200


def test_permissions(company, admin_client):
    for role in ("Менеджер", "Диспетчер", "Механик", "Водитель", "Бухгалтер"):
        api = api_with_role(company, role)
        assert api.patch(URL, {"theme": "dark"}, format="json").status_code == 403, role
    observer = api_with_role(company, "Наблюдатель")  # company.view есть
    assert observer.get(URL).status_code == 200
    assert observer.patch(URL, {"theme": "dark"}, format="json").status_code == 403
    assert api_with_role(company, "Менеджер").get(URL).status_code == 403
    assert APIClient().get(URL).status_code == 401
    assert APIClient().patch(URL, {}, format="json").status_code == 401
    assert admin_client.post(URL, {}, format="json").status_code == 405
    assert stored(company) is None


def test_subscription_states(company, admin_client):
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get(URL).status_code == 200
    r = admin_client.patch(URL, {"theme": "dark"}, format="json")
    assert r.status_code == 403 and r.data["code"] == "subscription_readonly"
    Subscription.objects.filter(company=company).update(
        status=Subscription.BLOCKED, ends_at=timezone.now() + timedelta(days=20)
    )
    assert admin_client.get(URL).data["code"] == "subscription_blocked"
    assert stored(company) is None


# --- логотип ---


def test_logo_upload_png_and_webp_and_jpeg(admin_client, company):
    r = upload(admin_client, "Логотип Компании.PNG", PNG)
    assert r.status_code == 200, r.content
    url = r.data["logo_url"]
    assert url.startswith(f"http://testserver{settings.MEDIA_URL}branding/{company.id}/")
    assert url.endswith(".png")
    name = stored(company).logo.name
    assert name.startswith(f"branding/{company.id}/") and disk(name)
    assert "Логотип" not in name  # имя файла клиента не используется
    for filename, content, ext in (("a.webp", WEBP, ".webp"), ("b.jpg", JPEG, ".jpg")):
        r = upload(admin_client, filename, content)
        assert r.status_code == 200 and r.data["logo_url"].endswith(ext), r.content
    assert upload(admin_client, "c.jpeg", JPEG).status_code == 200


@pytest.mark.parametrize(
    "name,content",
    [
        ("logo.svg", SVG),
        ("logo.svg", PNG),
        ("logo.png", SVG),  # расширение png, содержимое svg
        ("logo.png", JPEG),  # расширение и подпись не совпадают
        ("logo.jpg", PNG),
        ("logo.webp", PNG),
        ("logo.png", b"GIF89a" + b"\x00" * 20),
        ("logo.gif", b"GIF89a" + b"\x00" * 20),
        ("logo.html", b"<html><script>1</script></html>"),
        ("logo", PNG),
        ("logo.png", b""),
        ("logo.png", PNG[:4]),
        ("logo.png.exe", PNG),
        ("logo.png", PNG + b"\x00" * (1024 * 1024)),  # больше 1 МБ
    ],
)
def test_logo_rejections(admin_client, company, name, content):
    r = upload(admin_client, name, content)
    assert r.status_code == 400 and "logo" in r.data, (name, r.content)
    assert stored(company) is None or not stored(company).logo


def test_logo_exactly_1mb_is_accepted(admin_client):
    assert (
        upload(admin_client, "big.png", PNG + b"\x00" * (1024 * 1024 - len(PNG))).status_code == 200
    )


def test_logo_must_be_a_file(admin_client):
    r = admin_client.patch(URL, {"logo": "http://evil/x.png"}, format="json")
    assert r.status_code == 400 and "logo" in r.data


def test_path_traversal_name_is_neutralised(admin_client, company):
    r = upload(admin_client, "../../etc/evil.png", PNG)
    assert r.status_code == 200
    assert stored(company).logo.name.startswith(f"branding/{company.id}/")


def test_clear_logo_multipart_and_json_deletes_file(
    admin_client, company, django_capture_on_commit_callbacks
):
    upload(admin_client, "a.png", PNG)
    name = stored(company).logo.name
    with django_capture_on_commit_callbacks(execute=True):
        r = admin_client.patch(URL, {"logo": ""}, format="multipart")
    assert r.status_code == 200 and r.data["logo_url"] is None
    assert not stored(company).logo and not disk(name)
    upload(admin_client, "b.png", PNG)
    name = stored(company).logo.name
    with django_capture_on_commit_callbacks(execute=True):
        r = admin_client.patch(URL, {"logo": None}, format="json")
    assert r.status_code == 200 and r.data["logo_url"] is None and not disk(name)


def test_replacing_logo_deletes_old_file(admin_client, company, django_capture_on_commit_callbacks):
    upload(admin_client, "a.png", PNG)
    old = stored(company).logo.name
    with django_capture_on_commit_callbacks(execute=True):
        assert upload(admin_client, "b.png", PNG).status_code == 200
    new = stored(company).logo.name
    assert new != old and disk(new) and not disk(old)


def test_other_fields_keep_logo(admin_client, company):
    upload(admin_client, "a.png", PNG)
    name = stored(company).logo.name
    r = admin_client.patch(URL, {"theme": "dark"}, format="json")
    assert r.data["logo_url"] and stored(company).logo.name == name


def test_logo_isolation_between_companies(two):
    (a, _, api_a), (b, _, api_b) = two
    upload(api_a, "a.png", PNG)
    assert api_b.get(URL).data["logo_url"] is None
    assert upload(api_b, "b.png", PNG).status_code == 200
    assert stored(a).logo.name.startswith(f"branding/{a.id}/")
    assert stored(b).logo.name.startswith(f"branding/{b.id}/")
    assert stored(a).logo.name != stored(b).logo.name


# --- аудит ---


def test_audit_logs_field_names_never_file(admin_client, company):
    upload(admin_client, "a.png", PNG, theme="dark", primary_color="#010203")
    with tenant_context(company.id):
        row = AuditLog.objects.get(object_type="core.companybranding")
    assert row.action == "update" and row.user is not None
    assert row.changes["theme"] == ["system", "dark"]
    assert row.changes["primary_color"] == ["#2563EB", "#010203"]
    assert row.changes["logo"] == "changed"
    assert "png" not in str(row.changes) and "PNG" not in str(row.changes)
    assert set(row.changes) == {"theme", "primary_color", "logo"}
    admin_client.patch(URL, {"theme": "dark"}, format="json")  # без изменений
    with tenant_context(company.id):
        assert AuditLog.objects.filter(object_type="core.companybranding").count() == 1


def test_audit_is_per_company(two):
    (a, _, api_a), (b, _, api_b) = two
    api_a.patch(URL, {"theme": "light"}, format="json")
    with tenant_context(b.id):
        assert not AuditLog.objects.filter(object_type="core.companybranding").exists()
    with tenant_context(a.id):
        assert AuditLog.objects.filter(object_type="core.companybranding").count() == 1


# --- модель ---


def test_custom_domain_normalised_unique_and_lowercase_in_db(two):
    (a, *_), (b, *_) = two
    ba = CompanyBranding.objects.create(company=a, custom_domain="  Example.COM ")
    assert ba.custom_domain == "example.com"
    bb = CompanyBranding.objects.create(company=b, custom_domain="")
    assert bb.custom_domain is None
    with pytest.raises(IntegrityError), transaction.atomic():
        CompanyBranding.objects.filter(pk=bb.pk).update(custom_domain="example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        CompanyBranding.objects.filter(pk=bb.pk).update(custom_domain="MiXed.kz")
    with pytest.raises(IntegrityError), transaction.atomic():
        CompanyBranding.objects.filter(pk=bb.pk).update(custom_domain="")
    with pytest.raises(IntegrityError), transaction.atomic():
        CompanyBranding.objects.filter(pk=bb.pk).update(theme="neon")


def test_branding_is_outside_rls_by_design():
    assert "core_companybranding" not in rls.tenant_tables()
    assert not issubclass(CompanyBranding, TenantModel)
    assert settings.MEDIA_URL == "/media/"
    assert "logistix-test-media" in str(settings.MEDIA_ROOT)


# --- публичный эндпоинт ---


def set_domain(company, domain, **extra):
    return CompanyBranding.objects.update_or_create(
        company=company, defaults={"custom_domain": domain, **extra}
    )[0]


def test_public_defaults_for_unknown_empty_and_missing_host():
    for params in ({}, {"host": ""}, {"host": "   "}, {"host": "nobody.example.com"}):
        r = APIClient().get(PUBLIC, params)
        assert r.status_code == 200 and r.data == PLATFORM_DEFAULTS, params
    assert PLATFORM_DEFAULTS == {
        "app_name": "Logistix",
        "logo_url": None,
        "primary_color": "#2563EB",
        "theme": "system",
    }


def test_public_returns_branding_only_for_own_domain(two):
    (a, _, api_a), (b, _, api_b) = two
    upload(api_a, "a.png", PNG)
    api_a.patch(
        URL, {"app_name": "Альфа", "primary_color": "#112233", "theme": "dark"}, format="json"
    )
    set_domain(a, "login.alfa.kz")
    set_domain(b, "login.beta.kz", app_name="Бета")
    anon = APIClient()
    r = anon.get(PUBLIC, {"host": "login.alfa.kz"})
    assert r.status_code == 200
    assert set(r.data) == {"app_name", "logo_url", "primary_color", "theme"}
    assert r.data["app_name"] == "Альфа" and r.data["primary_color"] == "#112233"
    assert r.data["theme"] == "dark"
    assert r.data["logo_url"].startswith(f"http://testserver/media/branding/{a.id}/")
    rb = anon.get(PUBLIC, {"host": "login.beta.kz"})
    assert rb.data["app_name"] == "Бета" and rb.data["logo_url"] is None
    assert rb.data["primary_color"] == "#2563EB"
    assert (
        f"/{b.id}/" not in str(r.data) and "Co A" not in str(r.data) and "Co B" not in str(rb.data)
    )


@pytest.mark.parametrize(
    "host",
    [
        "LOGIN.Alfa.KZ",
        "  login.alfa.kz  ",
        "login.alfa.kz:8443",
        "login.alfa.kz.",
        "Login.ALFA.kz:80",
    ],
)
def test_public_normalises_host(company, host):
    set_domain(company, "login.alfa.kz", app_name="Альфа")
    assert APIClient().get(PUBLIC, {"host": host}).data["app_name"] == "Альфа"


@pytest.mark.parametrize(
    "host",
    [
        "' OR 1=1 --",
        "login.alfa.kz'; DROP TABLE core_companybranding;--",
        "логин.альфа.рф",
        "💥" * 40,
        "%00",
        "a" * 255,
        "login.alfa.kz/../x",
        "login.alfa.kz:abc",
        "[::1]:8000",
        ":::",
    ],
)
def test_public_garbage_host_gets_defaults(company, host):
    set_domain(company, "login.alfa.kz", app_name="Альфа")
    r = APIClient().get(PUBLIC, {"host": host})
    assert r.status_code == 200 and r.data == PLATFORM_DEFAULTS, host


def test_public_too_long_host_is_400():
    r = APIClient().get(PUBLIC, {"host": "a" * 256})
    assert r.status_code == 400 and "host" in r.data


def test_public_blank_app_name_falls_back_to_platform_name(company):
    set_domain(company, "x.kz", primary_color="#FF0000")
    r = APIClient().get(PUBLIC, {"host": "x.kz"})
    assert r.data["app_name"] == "Logistix" and r.data["primary_color"] == "#FF0000"


def test_public_needs_no_auth_and_ignores_bad_token(company):
    set_domain(company, "x.kz", app_name="Икс")
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION="Bearer garbage")
    assert api.get(PUBLIC, {"host": "x.kz"}).data["app_name"] == "Икс"


def test_public_is_get_only(company):
    for method in ("post", "patch", "put", "delete"):
        assert getattr(APIClient(), method)(PUBLIC).status_code == 405, method


def test_public_ignores_subscription_state(company):
    set_domain(company, "x.kz", app_name="Икс")
    Subscription.objects.filter(company=company).update(status=Subscription.BLOCKED)
    assert APIClient().get(PUBLIC, {"host": "x.kz"}).data["app_name"] == "Икс"


def test_public_is_throttled(monkeypatch):
    monkeypatch.setattr(BrandingThrottle, "THROTTLE_RATES", {"branding": "3/min"})
    api = APIClient()
    codes = [api.get(PUBLIC, {"host": "x.kz"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_public_query_count(company, django_assert_max_num_queries):
    set_domain(company, "x.kz")
    with django_assert_max_num_queries(3):  # поиск + SAVEPOINT/RELEASE
        APIClient().get(PUBLIC, {"host": "x.kz"})
    with django_assert_max_num_queries(3):  # поиск + SAVEPOINT/RELEASE
        APIClient().get(PUBLIC, {"host": "unknown.kz"})


def test_branding_works_under_app_role(db):
    from apps.core.services import create_company_with_defaults
    from apps.core.tests.test_rls import app_role
    from conftest import TEST_PASSWORD

    with app_role():
        admin = User.objects.create_user(email="rls-br@x.kz", password=TEST_PASSWORD)
        company = create_company_with_defaults("RLS Br", admin, ["forwarding"])
        api = APIClient()
        resp = api.post("/api/auth/login/", {"login": "rls-br@x.kz", "password": TEST_PASSWORD})
        assert resp.status_code == 200, resp.content
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        assert api.patch(URL, {"theme": "dark"}, format="json").status_code == 200
        set_domain(company, "rls.kz")
        # публичный эндпоинт читает таблицу без контекста компании
        assert APIClient().get(PUBLIC, {"host": "rls.kz"}).data["theme"] == "dark"
