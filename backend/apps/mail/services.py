"""Исходящая почта: проверка SMTP-сервера, подстановки шаблона, отправка письма компании."""

import ipaddress
import re
import smtplib
import socket
import ssl
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage, get_connection
from django.core.validators import validate_email
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.documents import services as document_services

from . import crypto
from .models import MailAccount, MailAttachment, MailMessage

ALLOWED_PORTS = {25, 465, 587, 2525}
MAX_RECIPIENTS = 10
MAX_ATTACHMENTS = 5
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
PLACEHOLDERS = (
    "company_name", "client_name", "order_number", "trip_number", "carrier_name", "sender_name",
)  # fmt: skip


class MailNotConfigured(APIException):
    status_code = 409
    default_detail = "Почтовый ящик компании не настроен или выключен"
    default_code = "mail_not_configured"


class MailLimitReached(APIException):
    status_code = 429
    default_detail = "Достигнут суточный предел писем компании"
    default_code = "mail_daily_limit"


def render_template(text: str, context: dict) -> str:
    """Подставляет {{ имя }} из разрешённого набора; неизвестное имя остаётся как есть."""
    return PLACEHOLDER.sub(lambda m: str(context.get(m.group(1), m.group(0))), text or "")


def clean_addresses(values, field: str, *, required: bool) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError({field: "Ожидается список адресов"})
    out: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise ValidationError({field: "Адрес должен быть строкой"})
        value = raw.strip()
        if not value:
            continue
        if "\n" in value or "\r" in value or "," in value:
            raise ValidationError({field: f"Некорректный адрес: {value[:60]}"})
        try:
            validate_email(value)
        except DjangoValidationError:
            raise ValidationError({field: f"Некорректный адрес: {value[:60]}"}) from None
        if value.lower() not in {x.lower() for x in out}:
            out.append(value)
    if required and not out:
        raise ValidationError({field: "Укажите хотя бы одного получателя"})
    if len(out) > MAX_RECIPIENTS:
        raise ValidationError({field: f"Не больше {MAX_RECIPIENTS} адресов"})
    return out


def ensure_public_host(host: str) -> None:
    """SMTP-сервер не должен указывать во внутреннюю сеть (защита от SSRF)."""
    if getattr(settings, "MAIL_ALLOW_PRIVATE_HOSTS", False):
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise ValidationError({"host": "Не удалось найти SMTP-сервер по этому адресу"}) from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValidationError(
                {"host": "Адрес сервера ведёт во внутреннюю сеть: он не разрешён"}
            )


def validate_account_fields(host: str, port: int) -> None:
    if port not in ALLOWED_PORTS:
        raise ValidationError(
            {"port": f"Допустимые порты: {', '.join(map(str, sorted(ALLOWED_PORTS)))}"}
        )
    ensure_public_host(host)


def _connection(account: MailAccount):
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=account.host,
        port=account.port,
        username=account.username or None,
        password=crypto.decrypt(account.password_enc) or None,
        use_ssl=account.security == MailAccount.SSL,
        use_tls=account.security == MailAccount.STARTTLS,
        timeout=getattr(settings, "MAIL_SMTP_TIMEOUT", 15),
        fail_silently=False,
    )


def _from_header(account: MailAccount) -> str:
    name = account.from_name.replace("\n", " ").replace("\r", " ").replace('"', "").strip()
    return f'"{name}" <{account.from_email}>' if name else account.from_email


def _short_error(exc: Exception) -> str:
    """Короткая причина без секретов: класс ошибки и начало сообщения сервера."""
    text = " ".join(str(exc).split())[:200]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _daily_count() -> int:
    since = timezone.now() - timedelta(days=1)
    return MailMessage.objects.filter(state=MailMessage.SENT, sent_at__gte=since).count()


def send_message(message: MailMessage, *, account: MailAccount | None = None) -> MailMessage:
    """Отправляет письмо ящиком компании и записывает результат (sent или failed + причина)."""
    account = account or MailAccount.objects.first()
    if account is None or not account.is_active:
        raise MailNotConfigured()
    if _daily_count() >= getattr(settings, "MAIL_DAILY_LIMIT", 200):
        raise MailLimitReached()
    email = EmailMessage(
        subject=message.subject,
        body=message.body,
        from_email=_from_header(account),
        to=list(message.to),
        cc=list(message.cc),
        connection=_connection(account),
    )
    for att in message.attachments.select_related("document__template_version"):
        if att.document is None:
            continue
        content, content_type, name = document_services.render_issued(att.document, "docx")
        email.attach(att.filename or name, content, content_type)
    message.attempts += 1
    try:
        email.send(fail_silently=False)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        message.state = MailMessage.FAILED
        message.error = _short_error(exc)
    else:
        message.state = MailMessage.SENT
        message.error = ""
        message.sent_at = timezone.now()
    message.save(update_fields=["state", "error", "sent_at", "attempts"])
    return message


def attach_documents(message: MailMessage, documents) -> None:
    if len(documents) > MAX_ATTACHMENTS:
        raise ValidationError({"attachments": f"Не больше {MAX_ATTACHMENTS} вложений"})
    for doc in documents:
        MailAttachment.objects.create(
            message=message, document=doc, filename=f"{doc.number or doc.kind}.docx"
        )
