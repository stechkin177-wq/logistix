"""Почта компании: ящик (шифрование пароля), SSRF, шаблоны, отправка, права, изоляция."""

import smtplib
from unittest import mock

import pytest
from django.core import mail as django_mail
from django.test import override_settings

from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.forwarding.tests.test_orders import make_client, make_order
from apps.forwarding.tests.test_parties import client_with_role
from apps.mail import crypto
from apps.mail import services as _services
from apps.mail.models import MailAccount, MailMessage

REAL_GUARD = _services.ensure_public_host  # до подмены в фикстуре

pytestmark = pytest.mark.django_db

ACCOUNT = "/api/mail/account/"
MESSAGES = "/api/mail/messages/"
TEMPLATES = "/api/mail/templates/"
GOOD = {
    "host": "smtp.example.com", "port": 587, "security": "starttls", "username": "u",
    "password": "s3cret-pass", "from_email": "office@example.com", "from_name": "Логистика",
}  # fmt: skip


@pytest.fixture(autouse=True)
def _public_host_and_locmem():
    """Тесты не ходят в сеть: DNS-проверка подменена, письма уходят в locmem."""
    with (
        mock.patch("apps.mail.services.ensure_public_host", lambda host: None),
        override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"),
        mock.patch(
            "apps.mail.services._connection",
            lambda account: django_mail.get_connection(
                "django.core.mail.backends.locmem.EmailBackend"
            ),
        ),
    ):
        yield


def setup_account(api, **over):
    r = api.put(ACCOUNT, {**GOOD, **over}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


def send(api, **over):
    data = {"to": ["a@client.kz"], "subject": "Тема", "body": "Текст", **over}
    return api.post(MESSAGES, data, format="json")


def test_password_is_encrypted_and_never_returned(admin_client, company):
    body = setup_account(admin_client)
    assert body["has_password"] is True and "password" not in body
    assert "s3cret" not in str(admin_client.get(ACCOUNT).json())
    with tenant_context(company.id):
        acc = MailAccount.objects.get()
        assert (
            "s3cret" not in acc.password_enc and crypto.decrypt(acc.password_enc) == "s3cret-pass"
        )
    # пустой пароль при изменении - прежний сохраняется
    admin_client.put(ACCOUNT, {**GOOD, "password": "", "from_name": "Новое"}, format="json")
    with tenant_context(company.id):
        assert crypto.decrypt(MailAccount.objects.get().password_enc) == "s3cret-pass"
    with tenant_context(company.id):
        assert "s3cret" not in str(list(AuditLog.objects.values("changes")))


def test_account_validation_ports_and_ssrf(admin_client):
    assert admin_client.put(ACCOUNT, {**GOOD, "port": 22}, format="json").status_code == 400
    assert admin_client.put(ACCOUNT, {**GOOD, "security": "x"}, format="json").status_code == 400


def test_ssrf_guard_rejects_private_hosts():
    from rest_framework.exceptions import ValidationError

    for host in ("127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1", "localhost"):
        with pytest.raises(ValidationError):
            REAL_GUARD(host)


def test_send_records_sent_and_links(admin_client, company):
    setup_account(admin_client)
    client = make_client(company)
    order = make_order(company, client)
    r = send(admin_client, order=order.pk, client=client.pk, cc=["b@client.kz"])
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["state"] == "sent" and body["sent_at"] and body["order"] == order.pk
    assert len(django_mail.outbox) == 1
    assert django_mail.outbox[0].to == ["a@client.kz"] and django_mail.outbox[0].cc == [
        "b@client.kz"
    ]
    listed = admin_client.get(f"{MESSAGES}?order={order.pk}").json()
    assert listed["count"] == 1


def test_send_failure_is_recorded_without_secrets_and_retry(admin_client):
    setup_account(admin_client)
    boom = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    with mock.patch("django.core.mail.message.EmailMessage.send", side_effect=boom):
        r = send(admin_client)
    assert r.status_code == 201 and r.json()["state"] == "failed"
    assert "s3cret" not in r.json()["error"] and "SMTPAuthenticationError" in r.json()["error"]
    again = admin_client.post(f"{MESSAGES}{r.json()['id']}/send/")
    assert again.status_code == 200 and again.json()["state"] == "sent"
    assert again.json()["attempts"] == 2
    assert (
        admin_client.post(f"{MESSAGES}{r.json()['id']}/send/").status_code == 400
    )  # уже отправлено


def test_not_configured_and_draft(admin_client):
    assert send(admin_client).status_code == 409
    r = send(admin_client, send=False)
    assert r.status_code == 201 and r.json()["state"] == "draft"
    assert django_mail.outbox == []


def test_validation_of_recipients_subject_and_limits(admin_client):
    setup_account(admin_client)
    assert send(admin_client, to=[]).status_code == 400
    assert send(admin_client, to=["не-адрес"]).status_code == 400
    assert send(admin_client, to=["a@b.kz\nBcc: x@y.kz"]).status_code == 400
    assert send(admin_client, to=[f"u{i}@b.kz" for i in range(11)]).status_code == 400
    assert send(admin_client, subject="a\nb").status_code == 400
    assert send(admin_client, subject="").status_code == 400
    assert send(admin_client, order=999999).status_code == 400
    with override_settings(MAIL_DAILY_LIMIT=1):
        assert send(admin_client).status_code == 201
        assert send(admin_client).status_code == 429


def test_templates_render_placeholders(admin_client, company):
    setup_account(admin_client)
    client = make_client(company, name="ТОО Ромашка")
    order = make_order(company, client)
    t = admin_client.post(
        TEMPLATES,
        {
            "name": "Счёт",
            "subject": "Заказ {{ order_number }}",
            "body": "{{client_name}} {{ evil }}",
        },
        format="json",
    )
    assert t.status_code == 201, t.content
    dup = admin_client.post(TEMPLATES, {"name": "счёт"}, format="json")
    assert dup.status_code == 400
    r = admin_client.post(
        f"{TEMPLATES}{t.json()['id']}/render/", {"order": order.pk}, format="json"
    )
    assert r.status_code == 200
    assert order.number in r.json()["subject"] and "ТОО Ромашка" in r.json()["body"]
    assert "{{ evil }}" in r.json()["body"]  # неизвестное имя не подставляется


def test_permissions(company):
    _, admin = client_with_role(company, "Администратор")
    _, manager = client_with_role(company, "Менеджер")
    _, observer = client_with_role(company, "Наблюдатель")
    _, accountant = client_with_role(company, "Бухгалтер")
    setup_account(admin)
    assert manager.get(ACCOUNT).status_code == 403  # настройка ящика - только mail.manage_account
    assert manager.put(ACCOUNT, GOOD, format="json").status_code == 403
    assert send(manager).status_code == 201
    assert manager.get(MESSAGES).status_code == 200
    for who in (observer, accountant):
        assert send(who).status_code == 403
        assert who.get(MESSAGES).status_code == 403
        assert who.get("/api/mail/status/").status_code == 403
    assert manager.get("/api/mail/status/").json()["configured"] is True
    # менеджер подставляет шаблон в письмо, но создавать и менять шаблоны не может
    tpl = admin.post(
        TEMPLATES, {"name": "Т", "subject": "{{ company_name }}", "body": "-"}, format="json"
    ).json()
    assert manager.get(TEMPLATES).status_code == 200
    assert manager.post(f"{TEMPLATES}{tpl['id']}/render/", {}, format="json").status_code == 200
    assert manager.post(TEMPLATES, {"name": "Т2"}, format="json").status_code == 403
    assert manager.delete(f"{TEMPLATES}{tpl['id']}/").status_code == 403
    for who in (observer, accountant):
        assert who.post(f"{TEMPLATES}{tpl['id']}/render/", {}, format="json").status_code == 403


def test_isolation_between_companies(make_company):
    a, _, api_a = make_company("A")
    b, _, api_b = make_company("B")
    setup_account(api_a)
    mid = send(api_a).json()["id"]
    assert api_b.get(MESSAGES).json()["count"] == 0
    assert api_b.get(f"{MESSAGES}{mid}/").status_code == 404
    assert api_b.post(f"{MESSAGES}{mid}/send/").status_code == 404
    assert api_b.get(ACCOUNT).json() == {"configured": False}
    assert send(api_b).status_code == 409  # у компании B нет ящика
    with tenant_context(b.id):
        assert MailMessage.objects.count() == 0
