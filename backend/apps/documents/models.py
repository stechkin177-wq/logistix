from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TenantModel

KINDS = ["contract", "order_request", "carrier_order", "act", "invoice_print", "cmr", "letter"]
NUMBERED_KINDS = ["contract", "carrier_order", "act", "cmr", "letter"]

KIND_CHOICES = [(k, k) for k in KINDS]


class DocumentTemplate(TenantModel):
    """Шаблон документа компании: вид + язык; активный шаблон один на пару."""

    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    name = models.CharField(max_length=200)
    language = models.CharField(max_length=8, default="ru")
    is_active = models.BooleanField(default=True)
    current_version = models.ForeignKey(
        "documents.DocumentTemplateVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["kind", "language", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "kind", "language"],
                condition=Q(is_active=True),
                name="doctemplate_active_uniq",
            ),
            models.CheckConstraint(condition=Q(kind__in=KINDS), name="doctemplate_kind_valid"),
        ]

    def __str__(self):
        return f"{self.kind}/{self.language}: {self.name}"


class DocumentTemplateVersion(TenantModel):
    """Неизменяемая версия файла шаблона (docx)."""

    template = models.ForeignKey(
        DocumentTemplate, on_delete=models.CASCADE, related_name="versions"
    )
    number = models.PositiveIntegerField()
    content = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    is_starter = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["template", "-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "number"], name="doctemplateversion_number_uniq"
            ),
            models.CheckConstraint(
                condition=~Q(content=b""),
                name="doctemplateversion_content_not_empty",
            ),
        ]

    def __str__(self):
        return f"{self.template_id} v{self.number}"


class IssuedDocument(TenantModel):
    """Журнал выданных документов: версия шаблона, номер, снимок данных (JSON)."""

    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    template_version = models.ForeignKey(
        DocumentTemplateVersion, on_delete=models.PROTECT, related_name="+"
    )
    number = models.CharField(max_length=64, blank=True)
    issue_date = models.DateField()
    language = models.CharField(max_length=8, default="ru")
    client = models.ForeignKey(
        "forwarding.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    order = models.ForeignKey(
        "forwarding.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    invoice = models.ForeignKey(
        "finance.Invoice", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    snapshot = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issue_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "kind", "number"],
                condition=Q(kind__in=NUMBERED_KINDS),
                name="issueddocument_numbered_uniq",
            ),
            models.CheckConstraint(condition=Q(kind__in=KINDS), name="issueddocument_kind_valid"),
        ]

    def __str__(self):
        return f"{self.kind} {self.number}"
