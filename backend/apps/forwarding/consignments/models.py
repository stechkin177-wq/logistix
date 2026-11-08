from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TenantModel


class Consignment(TenantModel, SoftDeleteModel):
    """Груз заказа. Скрыт, пока удалён его заказ; восстановить груз удалённого заказа нельзя."""

    order = models.ForeignKey(
        "forwarding.Order", on_delete=models.PROTECT, related_name="consignments"
    )
    name = models.CharField(max_length=255)
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    volume_m3 = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    pallets = models.PositiveIntegerField(default=0)
    packaging = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника packaging",
    )
    status = models.ForeignKey(
        "core.HandbookValue",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника consignment_status",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["company", "order"], name="consignment_company_order_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(weight_kg__gte=0), name="consignment_weight_gte_0"),
            models.CheckConstraint(condition=Q(volume_m3__gte=0), name="consignment_volume_gte_0"),
        ]

    def __str__(self):
        return self.name

    @property
    def stops(self):
        """Остановки маршрута по порядку (имя ``points`` - прежнее related_name)."""
        return self.points.all()

    def restore_blocker(self) -> str | None:
        """Причина, по которой груз нельзя восстановить из корзины (None - можно)."""
        from .. import models as forwarding_models

        if forwarding_models.Order.trash.filter(pk=self.order_id).exists():
            return "Нельзя восстановить груз: его заказ удалён. Сначала восстановите заказ"
        return None


class ConsignmentPoint(TenantModel):
    """Остановка маршрута груза (в коде также ``ConsignmentStop``).

    Маршрут груза - упорядоченный по ``seq`` список остановок: начинается остановкой ``load`` и
    заканчивается ``unload`` (это правило проверяет сервис, а не БД, чтобы маршрут можно было
    править по шагам). Имя модели и таблица прежние (``ConsignmentPoint``); прежняя схема
    «одна погрузка + одна выгрузка» - частный случай (seq 1 и 2).

    Доли ``weight_kg``/``volume_m3``/``pallets`` - сколько груза грузится/выгружается на
    остановке; пусто (NULL) - весь груз.
    """

    LOAD = "load"
    UNLOAD = "unload"
    TRANSIT = "transit"
    TRANSFER = "transfer"
    CUSTOMS = "customs"
    KINDS = [
        (LOAD, "Погрузка"),
        (UNLOAD, "Выгрузка"),
        (TRANSIT, "Промежуточная"),
        (TRANSFER, "Передача/перегрузка"),
        (CUSTOMS, "Граница/таможня"),
    ]
    KIND_CODES = [code for code, _ in KINDS]

    PLANNED = "planned"
    ARRIVED = "arrived"
    DONE = "done"
    SKIPPED = "skipped"
    STATUSES = [
        (PLANNED, "Запланирована"),
        (ARRIVED, "Прибыли"),
        (DONE, "Выполнена"),
        (SKIPPED, "Пропущена"),
    ]
    STATUS_CODES = [code for code, _ in STATUSES]

    consignment = models.ForeignKey(Consignment, on_delete=models.CASCADE, related_name="points")
    # порядок остановки в маршруте груза (1..N); уникален в грузе. Если не задан при создании,
    # save() ставит следующий номер (сервисы маршрута всегда задают его сами).
    seq = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=8, choices=KINDS)
    status = models.CharField(max_length=8, choices=STATUSES, default=PLANNED)
    arrived_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    volume_m3 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    pallets = models.PositiveIntegerField(null=True, blank=True)
    window_from = models.DateTimeField()
    window_to = models.DateTimeField(null=True, blank=True)
    country = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника country",
    )
    city = models.CharField(max_length=255, blank=True)
    street = models.CharField(max_length=255, blank=True)
    method = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника loading_method",
    )
    contact = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=16, blank=True)
    lat = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    lng = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["seq", "id"]
        indexes = [
            models.Index(
                fields=["company", "consignment", "seq"], name="point_company_cons_seq_idx"
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["consignment", "seq"], name="point_consignment_seq_uniq"
            ),
            models.CheckConstraint(condition=Q(seq__gte=1), name="point_seq_gte_1"),
            models.CheckConstraint(
                condition=Q(kind__in=["load", "unload", "transit", "transfer", "customs"]),
                name="point_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["planned", "arrived", "done", "skipped"]),
                name="point_status_valid",
            ),
            models.CheckConstraint(
                condition=(Q(weight_kg__isnull=True) | Q(weight_kg__gte=0))
                & (Q(volume_m3__isnull=True) | Q(volume_m3__gte=0)),
                name="point_share_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(window_to__isnull=True) | Q(window_to__gte=models.F("window_from")),
                name="point_window_order",
            ),
            models.CheckConstraint(
                condition=Q(lat__isnull=True) | (Q(lat__gte=-90) & Q(lat__lte=90)),
                name="point_lat_range",
            ),
            models.CheckConstraint(
                condition=Q(lng__isnull=True) | (Q(lng__gte=-180) & Q(lng__lte=180)),
                name="point_lng_range",
            ),
        ]

    def __str__(self):
        return f"{self.consignment_id}:{self.seq} {self.kind} {self.city}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.seq:
            last = (
                ConsignmentPoint.objects.filter(consignment_id=self.consignment_id)
                .order_by("-seq")
                .values_list("seq", flat=True)
                .first()
            )
            self.seq = (last or 0) + 1
        super().save(*args, **kwargs)


ConsignmentStop = ConsignmentPoint  # новое имя сущности; таблица и модель прежние
