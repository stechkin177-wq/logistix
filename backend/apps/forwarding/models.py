from django.conf import settings
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

    audit_masked_fields = ("bin_iin", "notes", "iban")

    name = models.CharField(max_length=255)
    bin_iin = models.CharField(max_length=12, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=ACTIVE)
    notes = models.TextField(blank=True)
    address = models.CharField(max_length=500, blank=True)
    bank = models.CharField(max_length=255, blank=True)
    iban = models.CharField(max_length=34, blank=True)
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


class BankAccount(TenantModel):
    """Банковский счёт клиента, перевозчика или нашего юрлица (ровно одного владельца).

    Единственный источник банковских реквизитов. Столбцы bank/iban владельца - зеркало счёта по
    умолчанию (пишет только apps.forwarding.requisites); они остаются для прежних читателей API
    и документов. IBAN в аудит не пишется (audit_masked_fields)."""

    audit_masked_fields = ("iban",)

    client = models.ForeignKey(
        "forwarding.Client",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="accounts",
    )
    carrier = models.ForeignKey(
        "forwarding.Carrier",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="accounts",
    )
    legal_entity = models.ForeignKey(
        "core.LegalEntity",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="accounts",
    )
    bank = models.CharField(max_length=255, blank=True)
    bic = models.CharField("БИК/SWIFT", max_length=16, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    kbe = models.CharField("Кбе", max_length=4, blank=True)
    currency = models.CharField("Код валюты", max_length=3, blank=True)
    is_default = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    OWNER_FIELDS = ("client", "carrier", "legal_entity")

    class Meta:
        ordering = ["-is_default", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(client__isnull=False, carrier__isnull=True, legal_entity__isnull=True)
                    | Q(client__isnull=True, carrier__isnull=False, legal_entity__isnull=True)
                    | Q(client__isnull=True, carrier__isnull=True, legal_entity__isnull=False)
                ),
                name="bankaccount_exactly_one_owner",
            ),
            models.UniqueConstraint(
                fields=["client"],
                condition=Q(is_default=True, client__isnull=False),
                name="bankaccount_client_one_default",
            ),
            models.UniqueConstraint(
                fields=["carrier"],
                condition=Q(is_default=True, carrier__isnull=False),
                name="bankaccount_carrier_one_default",
            ),
            models.UniqueConstraint(
                fields=["legal_entity"],
                condition=Q(is_default=True, legal_entity__isnull=False),
                name="bankaccount_entity_one_default",
            ),
        ]

    def __str__(self):
        return f"{self.bank} {self.iban}".strip()

    @property
    def owner(self):
        return self.client or self.carrier or self.legal_entity


class Contract(TenantModel, SoftDeleteModel):
    """Договор с клиентом или перевозчиком (ровно одна сторона).

    Единственный источник договоров. Order.contract_number остаётся текстом для прежних заказов и
    заполняется из выбранного договора. Файл договора по шаблону - Contract.document."""

    KINDS = [("main", "Основной"), ("supplement", "Дополнительное соглашение"), ("other", "Прочее")]
    MANUAL = "manual"
    IMPORTED = "imported"
    SOURCES = [(MANUAL, "Введён вручную"), (IMPORTED, "Перенесён из прежних данных")]

    client = models.ForeignKey(
        "forwarding.Client",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    carrier = models.ForeignKey(
        "forwarding.Carrier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    kind = models.CharField(max_length=16, choices=KINDS, default="main")
    number = models.CharField(max_length=64)
    date = models.DateField()
    valid_until = models.DateField(null=True, blank=True, help_text="Пусто - бессрочно")
    title = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)
    source = models.CharField(max_length=16, choices=SOURCES, default=MANUAL)
    # выданный по шаблону файл договора (вид contract); сам файл остаётся в журнале документов
    document = models.ForeignKey(
        "documents.IssuedDocument",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contracts",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(client__isnull=False) & Q(carrier__isnull=True))
                | (Q(client__isnull=True) & Q(carrier__isnull=False)),
                name="contract_exactly_one_party",
            ),
            models.UniqueConstraint(
                fields=["company", "client", "number"],
                condition=Q(deleted_at__isnull=True, client__isnull=False),
                name="contract_client_number_uniq",
            ),
            models.UniqueConstraint(
                fields=["company", "carrier", "number"],
                condition=Q(deleted_at__isnull=True, carrier__isnull=False),
                name="contract_carrier_number_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.number} от {self.date:%d.%m.%Y}"


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
from .consignments.models import (  # noqa: E402,F401
    Consignment,
    ConsignmentPoint,
    ConsignmentStop,
)
from .finance_lines.models import OrderService  # noqa: E402,F401
from .orders.models import Order, OrderStatusHistory  # noqa: E402,F401
from .tracking.models import CargoTransfer, ConsignmentEvent  # noqa: E402,F401
from .trips.models import Trip, TripConsignment  # noqa: E402,F401
