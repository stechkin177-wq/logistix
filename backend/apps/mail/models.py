from django.conf import settings
from django.db import models

from apps.core.models import TenantModel


class MailAccount(TenantModel):
    """Почтовый ящик компании для исходящих писем (SMTP). Один на компанию.

    Подключает сама компания (свой почтовый сервис): платного сервиса отправки мы не подключаем.
    Пароль хранится зашифрованным (apps.mail.crypto) и наружу не отдаётся."""

    SSL = "ssl"
    STARTTLS = "starttls"
    NONE = "none"
    SECURITY = [(SSL, "SSL/TLS"), (STARTTLS, "STARTTLS"), (NONE, "Без шифрования")]

    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(max_length=10, choices=SECURITY, default=STARTTLS)
    username = models.CharField(max_length=255, blank=True)
    password_enc = models.TextField(blank=True)
    from_email = models.EmailField()
    from_name = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company"], name="mailaccount_company_uniq"),
        ]

    def __str__(self):
        return self.from_email


class MailTemplate(TenantModel):
    """Шаблон письма с подстановками {{ order_number }}, {{ client_name }} и т. п."""

    name = models.CharField(max_length=120)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="mailtemplate_company_name_uniq"
            ),
        ]

    def __str__(self):
        return self.name


class MailMessage(TenantModel):
    """Исходящее письмо: тема, получатели, состояние отправки, привязка к записям."""

    DRAFT = "draft"
    SENT = "sent"
    FAILED = "failed"
    STATES = [(DRAFT, "Черновик"), (SENT, "Отправлено"), (FAILED, "Ошибка")]

    audit_masked_fields = ("to", "cc", "subject", "body")

    to = models.JSONField(default=list)
    cc = models.JSONField(default=list)
    subject = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    state = models.CharField(max_length=10, choices=STATES, default=DRAFT)
    error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    order = models.ForeignKey(
        "forwarding.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    client = models.ForeignKey(
        "forwarding.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["company", "state", "created_at"], name="mailmsg_state")]

    def __str__(self):
        return self.subject


class MailAttachment(TenantModel):
    """Вложение письма - выданный документ (файл формируется при отправке по шаблону)."""

    message = models.ForeignKey(MailMessage, on_delete=models.CASCADE, related_name="attachments")
    document = models.ForeignKey(
        "documents.IssuedDocument", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    filename = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]
