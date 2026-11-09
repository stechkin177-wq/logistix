"""T5-A: единый вход, платформенный контекст, роли владельца/администратора платформы."""

import time

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.billing.models import BillingEvent, Subscription
from apps.core import totp
from apps.core.models import Membership, User
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db

LOGIN = "/api/auth/login/"
PLANS = "/api/platform/plans/"


def current_code(user):
    user.refresh_from_db()
    return totp.code_for(user.totp_secret, int(time.time() // totp.STEP_SECONDS))


def fresh_code(user):
    """Код TOTP текущего шага; использованный при входе шаг сбрасывается (в рамках теста)."""
    User.objects.filter(pk=user.pk).update(totp_last_step=0)
    return current_code(user)


def login(email, password=TEST_PASSWORD):
    """Вход; платформенный аккаунт проходит и второй шаг (подключение/ввод кода TOTP)."""
    client = APIClient()
    r = client.post(LOGIN, {"login": email, "password": password}, format="json")
    body = r.json() if r.status_code == 200 else {}
    if body.get("challenge"):
        challenge = body["challenge"]
        if body.get("totp_setup_required"):
            assert (
                client.post(
                    "/api/auth/totp/setup/", {"challenge": challenge}, format="json"
                ).status_code
                == 200
            )
        user = User.objects.get(email=email.lower())
        User.objects.filter(pk=user.pk).update(
            totp_last_step=0
        )  # тест может входить в один и тот же шаг
        r = client.post(
            "/api/auth/totp/", {"challenge": challenge, "code": current_code(user)}, format="json"
        )
    if r.status_code == 200 and "access" in r.json():
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
    return client, r


def as_token(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def test_owner_logs_in_without_membership_and_lands_in_platform(make_platform_client):
    _, owner = make_platform_client("owner")
    assert not Membership.objects.filter(user=owner).exists()
    client, r = login(owner.email)
    assert r.status_code == 200
    body = r.json()
    assert body["context"] == "platform" and body["platform_role"] == "owner"
    assert body["companies"] == []
    s = client.get("/api/platform/session/")
    assert s.status_code == 200
    data = s.json()
    assert data["context"] == "platform" and data["user"]["platform_role"] == "owner"
    assert "platform.plans.manage" in data["permissions"]


def test_user_without_company_or_role_still_cannot_log_in():
    User.objects.create_user(email="nobody@x.kz", password=TEST_PASSWORD)
    _, r = login("nobody@x.kz")
    assert r.status_code == 403


def test_ordinary_company_user_gets_company_context_and_no_platform(make_company):
    _, admin, _ = make_company()
    client, r = login(admin.email)
    assert r.json()["context"] == "company"
    assert client.get("/api/session/").status_code == 200
    for url in (
        "/api/platform/session/",
        PLANS,
        "/api/platform/companies/",
        "/api/platform/history/",
        "/api/platform/catalog/",
    ):
        resp = client.get(url)
        assert resp.status_code == 403, url
        assert resp.json()["code"] == "platform_context_required"


def test_superuser_does_not_get_platform_rights(make_company):
    _, admin, _ = make_company()
    User.objects.filter(pk=admin.pk).update(is_superuser=True, is_staff=True)
    client, r = login(admin.email)
    assert r.json()["context"] == "company"
    assert client.get(PLANS).status_code == 403
    su = User.objects.create_superuser(email="su@x.kz", password=TEST_PASSWORD)
    assert su.platform_role == "" and su.is_platform_admin is False
    assert su.is_superuser is True
    _, r2 = login("su@x.kz")
    assert r2.status_code == 403  # ни роли, ни компании


def test_company_admin_cannot_switch_to_platform(make_company):
    _, _, client = make_company()
    r = client.post("/api/auth/switch-company/", {"context": "platform"}, format="json")
    assert r.status_code == 403


def test_platform_token_does_not_open_company_data(make_platform_client, make_company):
    make_company()
    client, _ = make_platform_client("owner")
    for url in ("/api/session/", "/api/roles/", "/api/users/", "/api/billing/usage/"):
        r = client.get(url)
        assert r.status_code == 403, url
        assert r.json()["code"] == "company_context_required"


def test_platform_admin_is_independent_of_tariffs_and_modules(make_platform_client, make_company):
    company, _, _ = make_company()
    Subscription.objects.filter(company=company).update(status="blocked")
    client, _ = make_platform_client("owner")
    assert client.get(PLANS).status_code == 200
    assert client.get(f"/api/platform/subscriptions/{company.pk}/").status_code == 200
    assert client.get("/api/platform/session/").status_code == 200


def test_roles_owner_full_admin_limited(make_platform_client, make_company):
    company, _, _ = make_company()
    owner, _ = make_platform_client("owner")
    admin, _ = make_platform_client("admin")
    # чтение доступно обоим
    for c in (owner, admin):
        assert c.get(PLANS).status_code == 200
        assert c.get("/api/platform/history/").status_code == 200
    # тарифы меняет только владелец
    body = {"code": "zz", "name": "ZZ", "price": "1", "currency": "KZT", "billing_type": "monthly"}
    assert admin.post(PLANS, body, format="json").status_code == 403
    assert owner.post(PLANS, body, format="json").status_code == 201
    # подписки: оба; блокировка компании: только владелец
    url = f"/api/platform/subscriptions/{company.pk}"
    assert admin.post(f"{url}/renew/", {"periods": 1}, format="json").status_code == 200
    assert admin.post(f"{url}/block/", {"reason": "x"}, format="json").status_code == 403
    assert owner.post(f"{url}/block/", {"reason": ""}, format="json").status_code == 400
    r = owner.post(f"{url}/block/", {"reason": "неоплата"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "blocked"
    ev = BillingEvent.objects.filter(kind="company", key=str(company.pk), action="block").get()
    assert ev.changes["reason"] == "неоплата" and ev.user is not None
    assert admin.post(f"{url}/unblock/", {"reason": "x"}, format="json").status_code == 403
    r = owner.post(f"{url}/unblock/", {"reason": "оплачено"}, format="json")
    assert r.status_code == 200 and r.json()["status"] != "blocked"


def test_role_is_checked_live_removed_role_loses_access(make_platform_client):
    client, user = make_platform_client("owner")
    assert client.get(PLANS).status_code == 200
    User.objects.filter(pk=user.pk).update(platform_role="")
    assert client.get(PLANS).status_code == 401  # платформенный доступ закрыт сразу
    assert client.get("/api/platform/session/").status_code == 401


def test_context_switching_keeps_isolation(make_company):
    company_a, admin, _ = make_company("A")
    company_b, _, _ = make_company("B")
    User.objects.filter(pk=admin.pk).update(platform_role="owner")
    Membership.objects.filter(user=admin).update(is_active=True)
    client, r = login(admin.email)
    assert r.json()["context"] == "platform"  # роль -> сначала Центр управления
    assert [c["id"] for c in r.json()["companies"]] == [company_a.id]
    # в свою компанию: токен компании, платформенные права не действуют
    sw = client.post("/api/auth/switch-company/", {"company_id": company_a.id}, format="json")
    assert sw.status_code == 200 and sw.json()["context"] == "company"
    in_company = as_token(sw.json()["access"])
    assert in_company.get("/api/session/").json()["company"]["id"] == company_a.id
    assert in_company.get(PLANS).status_code == 403
    # чужая компания недоступна
    bad = client.post("/api/auth/switch-company/", {"company_id": company_b.id}, format="json")
    assert bad.status_code == 403
    # обратно в платформу
    back = in_company.post(
        "/api/auth/switch-company/",
        {"context": "platform", "code": fresh_code(admin)},
        format="json",
    )
    assert back.status_code == 200 and back.json()["context"] == "platform"
    plat = as_token(back.json()["access"])
    assert plat.get(PLANS).status_code == 200
    assert plat.get("/api/session/").status_code == 403
    me = plat.get("/api/auth/me/").json()
    assert me["context"] == "platform" and me["company_id"] is None


def test_switch_requires_exactly_one_target(make_company):
    _, _, client = make_company()
    assert client.post("/api/auth/switch-company/", {}, format="json").status_code == 400
    r = client.post(
        "/api/auth/switch-company/", {"company_id": 1, "context": "platform"}, format="json"
    )
    assert r.status_code == 400


def test_platform_logins_and_switches_are_journaled(make_platform_client):
    _, owner = make_platform_client("owner")
    login(owner.email, "wrong-password")
    login(owner.email)
    actions = list(
        BillingEvent.objects.filter(kind="auth", key=str(owner.pk))
        .order_by("id")
        .values_list("action", flat=True)
    )
    assert actions == ["login_failed", "password_ok", "totp_enabled", "login"]
    ev = BillingEvent.objects.filter(kind="auth", action="login_failed").get()
    assert "ip" in ev.changes and "password" not in str(ev.changes)


def test_refresh_keeps_platform_context(make_platform_client):
    _, owner = make_platform_client("owner")
    _, r = login(owner.email)
    ref = APIClient().post("/api/auth/refresh/", {"refresh": r.json()["refresh"]}, format="json")
    assert ref.status_code == 200
    assert as_token(ref.json()["access"]).get("/api/platform/session/").status_code == 200


def test_commands_create_owner_and_set_role(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_PASSWORD", "very-long-pass-1")
    call_command(
        "create_platform_owner", "Boss@Example.kz", "--password-env", "PLATFORM_OWNER_PASSWORD"
    )
    boss = User.objects.get(email="boss@example.kz")
    assert boss.platform_role == "owner" and not Membership.objects.filter(user=boss).exists()
    plain = User.objects.create_user(email="p@x.kz", password=TEST_PASSWORD)
    call_command("set_platform_role", "p@x.kz", "admin")
    plain.refresh_from_db()
    assert plain.platform_role == "admin"
    call_command("set_platform_role", "p@x.kz", "none")
    plain.refresh_from_db()
    assert plain.platform_role == ""
    assert BillingEvent.objects.filter(kind="auth", action="platform_role").count() == 2


# --- TOTP владельца платформы -----------------------------------------------------------------


def start_login(email, password=TEST_PASSWORD):
    client = APIClient()
    return client, client.post(LOGIN, {"login": email, "password": password}, format="json")


def test_rfc6238_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"
    assert totp.code_for(secret, 59 // 30) == "287082"
    assert totp.verify(secret, "287082", now=59) == 1
    assert totp.verify(secret, "287082", last_step=1, now=59) is None  # шаг уже использован
    assert (
        totp.verify(secret, "28708", now=59) is None
        and totp.verify(secret, "abcdef", now=59) is None
    )


def test_owner_password_alone_gives_no_tokens_and_setup_enables_totp(make_platform_client):
    _, owner = make_platform_client("owner")
    client, r = start_login(owner.email)
    body = r.json()
    assert r.status_code == 200 and "access" not in body and "refresh" not in body
    assert body["totp_setup_required"] is True and body["totp_required"] is False
    # без кода доступа нет
    assert client.get("/api/platform/session/").status_code == 401
    setup = client.post(
        "/api/auth/totp/setup/", {"challenge": body["challenge"]}, format="json"
    ).json()
    assert (
        setup["otpauth_uri"].startswith("otpauth://totp/")
        and setup["secret"] in setup["otpauth_uri"]
    )
    owner.refresh_from_db()
    assert owner.totp_secret == setup["secret"] and owner.totp_enabled is False
    code = current_code(owner)
    ok = client.post(
        "/api/auth/totp/", {"challenge": body["challenge"], "code": code}, format="json"
    )
    assert ok.status_code == 200 and ok.json()["context"] == "platform"
    owner.refresh_from_db()
    assert owner.totp_enabled is True
    # следующий вход - уже запрос кода (не подключение)
    _, r2 = start_login(owner.email)
    assert r2.json()["totp_required"] is True and r2.json()["totp_setup_required"] is False


def test_wrong_code_is_rejected_journaled_and_replay_is_blocked(make_platform_client):
    _, owner = make_platform_client("owner")
    client, r = start_login(owner.email)
    ch = r.json()["challenge"]
    client.post("/api/auth/totp/setup/", {"challenge": ch}, format="json")
    bad = client.post("/api/auth/totp/", {"challenge": ch, "code": "000000"}, format="json")
    assert (
        bad.status_code == 401
        and bad.json()["code"] == "totp_invalid"
        and "access" not in bad.json()
    )
    assert BillingEvent.objects.filter(
        kind="auth", key=str(owner.pk), action="totp_failed"
    ).exists()
    code = current_code(owner)
    assert (
        client.post("/api/auth/totp/", {"challenge": ch, "code": code}, format="json").status_code
        == 200
    )
    # тот же код второй раз не принимается
    again = client.post("/api/auth/totp/", {"challenge": ch, "code": code}, format="json")
    assert again.status_code == 401


def test_totp_attempts_are_throttled(make_platform_client):
    from django.core.cache import cache

    cache.clear()
    _, owner = make_platform_client("owner")
    client, r = start_login(owner.email)
    ch = r.json()["challenge"]
    client.post("/api/auth/totp/setup/", {"challenge": ch}, format="json")
    codes = [
        client.post(
            "/api/auth/totp/", {"challenge": ch, "code": "000000"}, format="json"
        ).status_code
        for _ in range(8)
    ]
    assert 429 in codes
    cache.clear()


def test_challenge_is_required_valid_and_not_a_token(make_platform_client, make_company):
    _, owner = make_platform_client("owner")
    client = APIClient()
    assert (
        client.post(
            "/api/auth/totp/", {"challenge": "x", "code": "123456"}, format="json"
        ).status_code
        == 401
    )
    # талон обычного пользователя компании не подходит (второй фактор только платформе)
    _, admin, _ = make_company()
    from apps.core.api.auth import _challenge

    assert (
        client.post(
            "/api/auth/totp/setup/", {"challenge": _challenge(admin)}, format="json"
        ).status_code
        == 401
    )
    # сам талон не открывает API
    ch = start_login(owner.email)[1].json()["challenge"]
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {ch}")
    assert c.get("/api/platform/session/").status_code == 401


def test_platform_token_without_mfa_is_rejected_for_owner(make_platform_client):
    from apps.core.api.auth import issue_tokens

    _, owner = make_platform_client("owner")
    weak = as_token(issue_tokens(owner)["access"])  # без метки mfa
    assert weak.get("/api/platform/session/").status_code == 401
    assert (
        as_token(issue_tokens(owner, mfa=True)["access"]).get("/api/platform/session/").status_code
        == 200
    )


def test_switch_to_platform_needs_mfa_token_and_fresh_code_for_owner(make_company):
    from apps.core.api.auth import issue_tokens

    company, admin, _ = make_company("A")
    User.objects.filter(pk=admin.pk).update(
        platform_role="owner", totp_secret=totp.new_secret(), totp_enabled=True
    )
    url = "/api/auth/switch-company/"
    weak = as_token(issue_tokens(admin, company.id)["access"])  # токен без подтверждения TOTP
    assert weak.post(url, {"context": "platform"}, format="json").status_code == 403
    strong = as_token(issue_tokens(admin, company.id, mfa=True)["access"])
    no_code = strong.post(url, {"context": "platform"}, format="json")
    assert no_code.status_code == 403 and no_code.json()["code"] == "totp_required"
    wrong = strong.post(url, {"context": "platform", "code": "000000"}, format="json")
    assert wrong.status_code == 400 and wrong.json()["code"] == "totp_invalid"
    assert BillingEvent.objects.filter(action="totp_failed", changes__at="switch").exists()
    code = fresh_code(admin)
    ok = strong.post(url, {"context": "platform", "code": code}, format="json")
    assert ok.status_code == 200 and ok.json()["context"] == "platform"
    # тот же код повторно не принимается
    again = strong.post(url, {"context": "platform", "code": code}, format="json")
    assert again.status_code == 400


def test_admin_role_totp_is_optional_until_enabled(make_platform_client):
    _, admin = make_platform_client("admin")
    _, r = start_login(admin.email)
    assert "access" in r.json()  # без TOTP администратор входит по паролю
    User.objects.filter(pk=admin.pk).update(totp_enabled=True, totp_secret=totp.new_secret())
    _, r2 = start_login(admin.email)
    assert r2.json()["totp_required"] is True and "access" not in r2.json()


def test_reset_totp_command_clears_secret_and_revokes_tokens(make_platform_client):
    _, owner = make_platform_client("owner")
    client, r = login(owner.email)
    assert client.get("/api/platform/session/").status_code == 200
    time.sleep(1.1)  # отзыв считается с точностью до секунды
    call_command("reset_totp", owner.email)
    owner.refresh_from_db()
    assert owner.totp_secret == "" and owner.totp_enabled is False
    assert client.get("/api/platform/session/").status_code == 401
    assert BillingEvent.objects.filter(kind="auth", action="totp_reset").exists()
    # после сброса вход снова требует подключения
    assert start_login(owner.email)[1].json()["totp_setup_required"] is True


# --- отзыв токенов при выходе и смене пароля --------------------------------------------------


def test_logout_revokes_access_and_refresh(make_company):
    _, admin, _ = make_company("A")
    client, r = login(admin.email)
    refresh = r.json()["refresh"]
    assert client.get("/api/session/").status_code == 200
    time.sleep(1.1)
    assert client.post("/api/auth/logout/").status_code == 204
    assert client.get("/api/session/").status_code == 401
    ref = APIClient().post("/api/auth/refresh/", {"refresh": refresh}, format="json")
    assert ref.status_code == 401
    # новый вход работает
    client2, r2 = login(admin.email)
    assert client2.get("/api/session/").status_code == 200


def test_password_change_revokes_old_tokens_and_returns_new(make_company):
    _, admin, _ = make_company("A")
    old, r = login(admin.email)
    old_refresh = r.json()["refresh"]
    time.sleep(1.1)
    ch = old.post(
        "/api/auth/password/",
        {"old_password": TEST_PASSWORD, "new_password": "Brand-new-pass-77"},
        format="json",
    )
    assert ch.status_code == 200 and "access" in ch.json() and "refresh" in ch.json()
    # прежние токены (в том числе другого устройства) недействительны
    assert old.get("/api/session/").status_code == 401
    assert (
        APIClient().post("/api/auth/refresh/", {"refresh": old_refresh}, format="json").status_code
        == 401
    )
    # текущая сессия продолжается на новых токенах
    assert as_token(ch.json()["access"]).get("/api/session/").status_code == 200
    assert (
        APIClient()
        .post("/api/auth/refresh/", {"refresh": ch.json()["refresh"]}, format="json")
        .status_code
        == 200
    )


def test_refresh_keeps_mfa_mark(make_platform_client):
    _, owner = make_platform_client("owner")
    _, r = login(owner.email)
    ref = APIClient().post("/api/auth/refresh/", {"refresh": r.json()["refresh"]}, format="json")
    assert ref.status_code == 200
    assert as_token(ref.json()["access"]).get("/api/platform/session/").status_code == 200


def test_set_password_anywhere_revokes_tokens(make_company):
    """Штатная `manage.py changepassword` делает user.set_password(); токены тоже отзываются."""
    _, admin, _ = make_company("A")
    client, _ = login(admin.email)
    assert client.get("/api/session/").status_code == 200
    time.sleep(1.1)
    admin.refresh_from_db()
    admin.set_password("Another-pass-4455")
    admin.save()
    assert client.get("/api/session/").status_code == 401
    new_client, r = login(admin.email, "Another-pass-4455")
    assert new_client.get("/api/session/").status_code == 200


# --- установка пароля по одноразовой ссылке; один аккаунт на два уровня ---

SETUP = "/api/auth/password-setup/"


def link_parts(out: str):
    from urllib.parse import parse_qs, urlparse

    url = next(line for line in out.splitlines() if line.startswith("https://"))
    query = parse_qs(urlparse(url).query)
    return url, query["uid"][0], query["token"][0]


def make_owner_link(capsys, email="me@example.kz"):
    call_command(
        "create_platform_owner",
        email,
        "--full-name",
        "Тест",
        "--base-url",
        "https://app.example.kz",
    )
    return link_parts(capsys.readouterr().out)


def test_owner_is_created_without_password_and_sets_it_via_one_time_link(capsys):
    url, uid, token = make_owner_link(capsys)
    assert url.startswith("https://app.example.kz/setup-password?uid=")
    owner = User.objects.get(email="me@example.kz")
    assert owner.platform_role == "owner" and not owner.has_usable_password()
    assert not Membership.objects.filter(user=owner).exists()
    # до установки пароля войти нельзя
    assert start_login(owner.email, "anything")[1].status_code == 401
    api = APIClient()
    assert (
        api.post(
            SETUP, {"uid": uid, "token": token, "new_password": "123"}, format="json"
        ).status_code
        == 400
    )
    ok = api.post(
        SETUP, {"uid": uid, "token": token, "new_password": "My-own-pass-2026!"}, format="json"
    )
    assert ok.status_code == 204
    # ссылка одноразовая
    again = api.post(
        SETUP, {"uid": uid, "token": token, "new_password": "Other-pass-2026!!"}, format="json"
    )
    assert again.status_code == 400 and "token" in again.json()
    # теперь обычный вход: пароль -> подключение TOTP (сам владелец)
    _, r = start_login(owner.email, "My-own-pass-2026!")
    assert r.json()["totp_setup_required"] is True and "access" not in r.json()
    assert BillingEvent.objects.filter(kind="auth", action="password_set").exists()


def test_link_is_rejected_when_forged_expired_or_for_wrong_user(capsys, settings):
    _, uid, token = make_owner_link(capsys)
    api = APIClient()
    body = {"new_password": "My-own-pass-2026!"}
    assert (
        api.post(SETUP, {"uid": uid, "token": token + "x", **body}, format="json").status_code
        == 400
    )
    assert api.post(SETUP, {"uid": "MQ", "token": token, **body}, format="json").status_code == 400
    assert api.post(SETUP, {"uid": "!!", "token": token, **body}, format="json").status_code == 400
    settings.PASSWORD_RESET_TIMEOUT = -1  # срок действия истёк
    assert api.post(SETUP, {"uid": uid, "token": token, **body}, format="json").status_code == 400


def test_setup_attempts_are_throttled(capsys):
    from django.core.cache import cache

    cache.clear()
    _, uid, _ = make_owner_link(capsys)
    api = APIClient()
    codes = [
        api.post(
            SETUP, {"uid": uid, "token": "bad", "new_password": "x"}, format="json"
        ).status_code
        for _ in range(14)
    ]
    assert 429 in codes
    cache.clear()


def test_issue_password_link_resets_forgotten_password_without_seeing_it(make_company, capsys):
    _, admin, _ = make_company("A")
    old, _ = login(admin.email)
    time.sleep(1.1)
    call_command("issue_password_link", admin.email, "--base-url", "https://app.example.kz")
    _, uid, token = link_parts(capsys.readouterr().out)
    # пока человек не задал новый пароль, прежний работает
    assert login(admin.email)[0].get("/api/session/").status_code == 200
    r = APIClient().post(
        SETUP, {"uid": uid, "token": token, "new_password": "Fresh-pass-2026!!"}, format="json"
    )
    assert r.status_code == 204
    assert old.get("/api/session/").status_code == 401  # прежние токены отозваны
    assert login(admin.email)[1].status_code == 401  # старый пароль больше не подходит
    assert login(admin.email, "Fresh-pass-2026!!")[0].get("/api/session/").status_code == 200


def test_single_account_is_platform_owner_and_company_admin_with_independent_contexts(
    capsys, make_company
):
    """Один аккаунт: владелец платформы и администратор своей компании; контексты независимы."""
    _, uid, token = make_owner_link(capsys)
    APIClient().post(
        SETUP, {"uid": uid, "token": token, "new_password": "My-own-pass-2026!"}, format="json"
    )
    call_command(
        "bootstrap_company", "--name", "Моя транспортная", "--owner-login", "me@example.kz",
        "--allow-existing-user", "--profile", "carrier",
    )  # fmt: skip
    me = User.objects.get(email="me@example.kz")
    membership = Membership.objects.get(user=me)
    assert membership.role.name == "Администратор" and me.platform_role == "owner"
    assert me.is_superuser is False and me.is_staff is False
    # вход: сначала Центр управления, только после TOTP
    client, r = login("me@example.kz", "My-own-pass-2026!")
    assert r.json()["context"] == "platform"
    assert [c["id"] for c in r.json()["companies"]] == [membership.company_id]
    assert client.get(PLANS).status_code == 200
    assert (
        client.get("/api/session/").status_code == 403
    )  # платформенный токен не видит данные компании
    # в свою компанию без повторного кода: права администратора компании
    sw = client.post(
        "/api/auth/switch-company/", {"company_id": membership.company_id}, format="json"
    )
    company_client = as_token(sw.json()["access"])
    session = company_client.get("/api/session/").json()
    assert (
        session["role"]["name"] == "Администратор"
        and session["company"]["id"] == membership.company_id
    )
    assert company_client.get(PLANS).status_code == 403  # токен компании не даёт платформенных прав
    assert company_client.get("/api/platform/session/").status_code == 403
    # обратно в платформу - только со свежим кодом
    no_code = company_client.post(
        "/api/auth/switch-company/", {"context": "platform"}, format="json"
    )
    assert no_code.status_code == 403
    back = company_client.post(
        "/api/auth/switch-company/", {"context": "platform", "code": fresh_code(me)}, format="json"
    )
    assert back.status_code == 200 and as_token(back.json()["access"]).get(PLANS).status_code == 200
    # администратор компании без платформенной роли платформу не открывает
    _, _, plain = make_company("Чужая")
    assert plain.get(PLANS).status_code == 403
