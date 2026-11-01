from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TenantModel
from apps.core.phone import normalize_phone


class PartyBase(TenantModel, SoftDeleteModel):
    """Общее для клиента и перевозчика. БИН/ИИН и заметки - персональные данные ИП: в аудит
    их значения не пишутся (audit_masked_fields)."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    STATUSES = [(ACTIVE, "Активен"), (INACTIVE, "Неактивен")]

    audit_masked_fields = ("bin_iin", "notes")

    name = models.CharField(max_length=255)
    bin_iin = models.CharField(max_length=12, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=ACTIVE)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class Client(PartyBase):
    type = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника client_type",
    )
    credit_limit = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )

    class Meta:
        indexes = [models.Index(fields=["company", "name"], name="client_company_name_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "bin_iin"],
                condition=Q(deleted_at__isnull=True) & ~Q(bin_iin=""),
                name="client_company_bin_uniq",
            ),
            models.CheckConstraint(condition=Q(credit_limit__gte=0), name="client_credit_gte_0"),
        ]


class Carrier(PartyBase):
    type = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника carrier_type",
    )
    rating = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
    )

    class Meta:
        indexes = [models.Index(fields=["company", "name"], name="carrier_company_name_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "bin_iin"],
                condition=Q(deleted_at__isnull=True) & ~Q(bin_iin=""),
                name="carrier_company_bin_uniq",
            ),
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | (Q(rating__gte=0) & Q(rating__lte=5)),
                name="carrier_rating_0_5",
            ),
        ]


class Contact(TenantModel):
    """Контакт клиента или перевозчика (ровно одного). Не удаляется мягко: следует за родителем."""

    client = models.ForeignKey(
        Client, null=True, blank=True, on_delete=models.CASCADE, related_name="contacts"
    )
    carrier = models.ForeignKey(
        Carrier, null=True, blank=True, on_delete=models.CASCADE, related_name="contacts"
    )
    name = models.CharField(max_length=255)
    position = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(client__isnull=False) & Q(carrier__isnull=True))
                | (Q(client__isnull=True) & Q(carrier__isnull=False)),
                name="contact_exactly_one_parent",
            ),
        ]

    def __str__(self):
        return self.name

    def normalize(self):
        """Телефон приводится к +7XXXXXXXXXX, если разбирается, иначе остаётся как введён."""
        phone = (self.phone or "").strip()
        try:
            self.phone = normalize_phone(phone) if phone else ""
        except ValueError:
            self.phone = phone
        self.email = (self.email or "").strip().lower()

    def save(self, *args, **kwargs):
        self.normalize()
        super().save(*args, **kwargs)


# Заказы и грузы живут в подпакетах; импорт нужен, чтобы Django нашёл модели приложения.
from .consignments.models import Consignment, ConsignmentPoint  # noqa: E402,F401
from .finance_lines.models import OrderService  # noqa: E402,F401
from .orders.models import Order, OrderStatusHistory  # noqa: E402,F401
from .trips.models import Trip, TripConsignment  # noqa: E402,F401
