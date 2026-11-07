from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import SoftDeleteModel, TenantModel

from .errors import FinanceError


class ExchangeRate(TenantModel):
    """Курс валюты на дату (вводится вручную).

    quote_currency пуст - курс к тенге (так записаны все прежние курсы; для KZT записи не
    создаются: курс 1). Если quote_currency задан - прямой курс пары currency/quote_currency
    (курсы между валютами без тенге; если прямого курса нет, считается через тенге).
    """

    currency = models.ForeignKey(
        "core.HandbookValue",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника currency",
    )
    quote_currency = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Валюта котировки (значение справочника currency); пусто - тенге",
    )
    date = models.DateField()
    rate = models.DecimalField(max_digits=18, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "currency", "date"],
                condition=Q(quote_currency__isnull=True),
                name="exchangerate_kzt_uniq",
            ),
            models.UniqueConstraint(
                fields=["company", "currency", "quote_currency", "date"],
                condition=Q(quote_currency__isnull=False),
                name="exchangerate_pair_uniq",
            ),
            models.CheckConstraint(condition=Q(rate__gt=0), name="exchangerate_rate_gt_0"),
            models.CheckConstraint(
                condition=Q(quote_currency__isnull=True) | ~Q(currency=models.F("quote_currency")),
                name="exchangerate_currency_ne_quote",
            ),
        ]

    def __str__(self):
        return f"{self.currency_id} {self.date}: {self.rate}"


def _handbook_fk(code, **kwargs):
    return models.ForeignKey(
        "core.HandbookValue",
        on_delete=models.PROTECT,
        related_name="+",
        help_text=f"Значение справочника {code}",
        **kwargs,
    )


class Invoice(TenantModel, SoftDeleteModel):
    """Счёт: клиенту (out) или полученный от перевозчика (in).

    Суммы (total_*) и курс фиксируются при выставлении; пока счёт черновик, они нулевые.
    Просроченность и оплаченность - производные (см. invoices.display_status).
    """

    DIRECTIONS = [("out", "Клиенту"), ("in", "От перевозчика")]
    STATUSES = [("draft", "Черновик"), ("issued", "Выставлен"), ("cancelled", "Отменён")]

    direction = models.CharField(max_length=3, choices=DIRECTIONS)
    number = models.CharField(max_length=64, blank=True)
    external_number = models.CharField(max_length=128, blank=True)
    client = models.ForeignKey(
        "forwarding.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    carrier = models.ForeignKey(
        "forwarding.Carrier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    order = models.ForeignKey(
        "forwarding.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    currency = _handbook_fk("currency")
    vat_rate = _handbook_fk("vat_rate")
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    rate_to_kzt = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="draft")
    total_net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_gross = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    comment = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["company", "direction", "status"], name="invoice_cmp_dir_st_idx"),
            models.Index(fields=["company", "due_date"], name="invoice_cmp_due_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "direction", "number"],
                condition=~Q(number=""),
                name="invoice_company_dir_number_uniq",
            ),
            models.CheckConstraint(
                condition=(Q(direction="out") & Q(client__isnull=False) & Q(carrier__isnull=True))
                | (Q(direction="in") & Q(carrier__isnull=False) & Q(client__isnull=True)),
                name="invoice_direction_party",
            ),
            models.CheckConstraint(
                condition=Q(total_net__gte=0) & Q(total_vat__gte=0) & Q(total_gross__gte=0),
                name="invoice_totals_gte_0",
            ),
        ]

    def __str__(self):
        return self.number or f"черновик #{self.pk}"


class InvoiceItem(TenantModel):
    """Позиция счёта: сумма без НДС и ссылка на строку заказа (доход для out, расход для in)."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=255)
    amount_net = models.DecimalField(max_digits=14, decimal_places=2)
    # null у отменённого счёта: строка освобождается (её можно удалить и выставить заново), а
    # название и сумма позиции остаются снимком для истории
    line = models.ForeignKey(
        "forwarding.OrderService",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="invoice_items",
    )
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # новая модель дохода (для исходящих счетов); пусто у позиций прежнего учёта
    income = models.ForeignKey(
        "finance.Income",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="invoice_items",
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_net__gte=0), name="invoiceitem_amount_gte_0"),
        ]


class Payment(TenantModel, SoftDeleteModel):
    """Оплата по счёту (в валюте счёта); курс к тенге фиксируется на дату платежа."""

    METHODS = [("bank", "Банк"), ("cash", "Наличные"), ("other", "Прочее")]

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    rate_to_kzt = models.DecimalField(max_digits=18, decimal_places=6)
    method = models.CharField(max_length=10, choices=METHODS, default="bank")
    payment_ref = models.CharField(max_length=128, blank=True)
    comment = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]
        indexes = [models.Index(fields=["invoice", "date"], name="payment_invoice_date_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_gt_0"),
        ]

    def restore_blocker(self) -> str | None:
        """Восстановить оплату нельзя, если счёт не выставлен или не хватает остатка."""
        invoice = Invoice.all_objects.filter(pk=self.invoice_id).first()
        if invoice is None or invoice.deleted_at is not None or invoice.status != "issued":
            return "Счёт оплаты отменён или удалён: восстановить оплату нельзя"
        paid = Payment.objects.filter(invoice=invoice).aggregate(t=models.Sum("amount"))["t"] or 0
        if self.amount > invoice.total_gross - paid:
            return "Сумма оплаты больше остатка по счёту: восстановить оплату нельзя"
        return None

    def restore(self):
        # счёт блокируется: восстановление не должно разойтись с параллельной оплатой
        with transaction.atomic():
            Invoice.all_objects.select_for_update().filter(pk=self.invoice_id).first()
            if (reason := self.restore_blocker()) is not None:
                raise FinanceError("payment_not_restorable", reason, status_code=409)
            super().restore()


# --- Финансовая архитектура P0.1 (подзадача 1.4.1): только структура, без сервисов ---------------

BASE_CURRENCY_CODES = ("KZT", "RUB", "USD", "EUR")


def _user_fk(**kwargs):
    return models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", **kwargs
    )


class CompanyFinancialSettings(TenantModel):
    """Финансовые настройки компании (ровно одна строка на компанию).

    engine: legacy - прежний учёт (OrderService), shadow - новая запись параллельно, new - новая
    архитектура. Переключение на new требует даты cutover и completed_status (CHECK в БД);
    сами переключение и сверка - в сервисах следующих подзадач. base_currency - одна из
    KZT/RUB/USD/EUR (проверяется в clean()). allow_backdating по умолчанию True: это совместимо с
    текущим поведением (запрета обратного датирования сейчас нет).
    """

    ACCOUNTING_METHODS = [("ACCRUAL", "Метод начисления")]
    ENGINES = [("legacy", "Прежний учёт"), ("shadow", "Параллельная запись"), ("new", "Новый учёт")]
    INCOME_RECOGNITIONS = [("all_trips_completed", "После завершения всех активных рейсов")]
    EXPENSE_CREATION_MODES = [("manual", "Вручную"), ("on_assign", "При назначении перевозчика")]

    base_currency = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника currency (KZT, RUB, USD или EUR)",
    )
    accounting_method = models.CharField(
        max_length=16, choices=ACCOUNTING_METHODS, default="ACCRUAL"
    )
    default_vat_rate = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника vat_rate",
    )
    fiscal_year_start_month = models.PositiveSmallIntegerField(default=1)
    allow_backdating = models.BooleanField(default=True)
    engine = models.CharField(max_length=8, choices=ENGINES, default="legacy")
    cutover_date = models.DateField(null=True, blank=True)
    income_recognition = models.CharField(
        max_length=32, choices=INCOME_RECOGNITIONS, default="all_trips_completed"
    )
    completed_status = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника trip_status, завершающее рейс для признания дохода",
    )
    expense_creation_mode = models.CharField(
        max_length=16, choices=EXPENSE_CREATION_MODES, default="manual"
    )
    sync_carrier_price = models.BooleanField(default=True)
    updated_by = _user_fk()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "company financial settings"
        constraints = [
            models.UniqueConstraint(fields=["company"], name="finsettings_company_uniq"),
            models.CheckConstraint(
                condition=Q(fiscal_year_start_month__gte=1, fiscal_year_start_month__lte=12),
                name="finsettings_fy_month_1_12",
            ),
            models.CheckConstraint(
                condition=Q(engine__in=["legacy", "shadow", "new"]),
                name="finsettings_engine_valid",
            ),
            models.CheckConstraint(
                condition=~Q(engine="new")
                | (Q(cutover_date__isnull=False) & Q(completed_status__isnull=False)),
                name="finsettings_new_needs_cutover_status",
            ),
        ]

    def __str__(self):
        return f"Финансовые настройки компании {self.company_id} ({self.engine})"

    def clean(self):
        super().clean()
        errors = {}
        if self.base_currency_id is not None:
            cur = self.base_currency
            if cur.handbook.code != "currency" or cur.company_id != self.company_id:
                errors["base_currency"] = "Нужно значение справочника валют этой компании"
            elif cur.code not in BASE_CURRENCY_CODES:
                errors["base_currency"] = "Базовая валюта: KZT, RUB, USD или EUR"
        if self.completed_status_id is not None:
            st = self.completed_status
            if st.handbook.code != "trip_status" or st.company_id != self.company_id:
                errors["completed_status"] = "Нужен статус рейса этой компании"
        if self.default_vat_rate_id is not None:
            vat = self.default_vat_rate
            if vat.handbook.code != "vat_rate" or vat.company_id != self.company_id:
                errors["default_vat_rate"] = "Нужна ставка НДС этой компании"
        if self.engine == "new":
            if self.cutover_date is None:
                errors["cutover_date"] = "Для нового учёта нужна дата cutover"
            if self.completed_status_id is None:
                errors["completed_status"] = "Для нового учёта нужен завершающий статус рейса"
        if errors:
            raise ValidationError(errors)


class FinancialPeriod(TenantModel):
    """Финансовый месяц компании: открыт или закрыт (закрытие/открытие - в сервисе)."""

    STATUSES = [("open", "Открыт"), ("closed", "Закрыт")]

    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=8, choices=STATUSES, default="open")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = _user_fk()
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "year", "month"], name="finperiod_company_year_month_uniq"
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1, month__lte=12), name="finperiod_month_1_12"
            ),
            models.CheckConstraint(
                condition=Q(status__in=["open", "closed"]), name="finperiod_status_valid"
            ),
        ]

    def __str__(self):
        return f"{self.year}-{self.month:02d} ({self.status})"


class FinancialPeriodEvent(TenantModel):
    """История закрытий и повторных открытий периода; для открытия причина обязательна."""

    ACTIONS = [("close", "Закрытие"), ("reopen", "Повторное открытие")]

    period = models.ForeignKey(FinancialPeriod, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=8, choices=ACTIONS)
    at = models.DateTimeField(default=timezone.now)
    user = _user_fk()
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["period", "at"], name="finperiodevent_period_at_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=["close", "reopen"]), name="finperiodevent_action_valid"
            ),
            models.CheckConstraint(
                condition=~Q(action="reopen") | ~Q(reason=""),
                name="finperiodevent_reopen_needs_reason",
            ),
        ]

    def __str__(self):
        return f"{self.period_id} {self.action} {self.at:%Y-%m-%d}"


class FxSnapshot(models.Model):
    """Снимок курса и суммы в базовой валюте на дату признания (поля Income и Expense).

    Записывается один раз при признании и позже НЕ пересчитывается при обновлении курсов.
    fx_rate_source: same - валюта равна базовой, direct - прямой курс, via_kzt - через тенге,
    legacy_missing - курса при переносе не нашлось (base_amount пуст, сумма в исходной валюте
    остаётся и участвует в сверке).
    """

    FX_SOURCES = [
        ("same", "Валюта равна базовой"),
        ("direct", "Прямой курс"),
        ("via_kzt", "Через тенге"),
        ("legacy_missing", "Курс при переносе не найден"),
    ]

    fx_base_currency = models.ForeignKey(
        "core.HandbookValue", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    fx_rate = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    fx_rate_date = models.DateField(null=True, blank=True)
    fx_rate_source = models.CharField(max_length=16, choices=FX_SOURCES, blank=True)
    base_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        abstract = True


class Income(TenantModel, FxSnapshot):
    """Доход: перевозка по заказу (freight) или отдельная услуга (service).

    Доход перевозки признаётся после завершения всех активных рейсов заказа (дата - завершение
    последнего рейса); услуга - после фактического оказания и подтверждения. planned - ожидает
    признания, recognized - признан, void - аннулирован. На один заказ приходится не более одного
    неаннулированного дохода перевозки. legacy_line связывает доход со строкой OrderService
    при переносе (OrderService не удаляется до завершения миграции и сверки).
    """

    KINDS = [("freight", "Перевозка"), ("service", "Услуга")]
    STATUSES = [("planned", "Запланирован"), ("recognized", "Признан"), ("void", "Аннулирован")]
    BASES = [
        ("trip_completed", "Завершение рейса"),
        ("service_confirmed", "Подтверждение услуги"),
        ("legacy_line_date", "Дата строки прежнего учёта"),
        ("manual_adjustment", "Ручная корректировка"),
    ]

    order = models.ForeignKey("forwarding.Order", on_delete=models.PROTECT, related_name="incomes")
    kind = models.CharField(max_length=8, choices=KINDS)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=64, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.ForeignKey("core.HandbookValue", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=STATUSES, default="planned")
    recognized_on = models.DateField(null=True, blank=True)
    recognition_basis = models.CharField(max_length=24, choices=BASES, blank=True)
    delivered_on = models.DateField(null=True, blank=True)
    confirmed_by = _user_fk()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    trip = models.ForeignKey(
        "forwarding.Trip",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Рейс, последним завершивший доход",
    )
    legacy_line = models.OneToOneField(
        "forwarding.OrderService",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="finance_income",
    )
    void_reason = models.TextField(blank=True)
    created_by = _user_fk()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["company", "order"], name="income_company_order_idx"),
            models.Index(
                fields=["company", "status", "recognized_on"], name="income_cmp_status_recog_idx"
            ),
            models.Index(fields=["company", "recognized_on"], name="income_company_recog_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="income_amount_gte_0"),
            models.CheckConstraint(
                condition=~Q(status="recognized") | Q(recognized_on__isnull=False),
                name="income_recognized_needs_date",
            ),
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(kind="freight") & ~Q(status="void"),
                name="income_one_active_freight_per_order",
            ),
            models.CheckConstraint(
                condition=~Q(fx_rate_source="legacy_missing") | Q(base_amount__isnull=True),
                name="income_legacy_missing_no_base",
            ),
        ]

    def __str__(self):
        return f"Доход #{self.pk} {self.kind} {self.amount}"


class IncomeTrip(TenantModel):
    """Рейсы, участвующие в доходе перевозки (заказ может исполняться несколькими рейсами)."""

    income = models.ForeignKey(Income, on_delete=models.PROTECT, related_name="income_trips")
    trip = models.ForeignKey("forwarding.Trip", on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["income", "trip"], name="incometrip_income_trip_uniq"),
        ]


class Expense(TenantModel, FxSnapshot):
    """Расход: перевозчику за рейс (carrier_transport) или прочий (other).

    Расход перевозчику связан с рейсом и перевозчиком; на рейс приходится не более одного
    активного такого расхода. source: carrier_price_sync - создан/скорректирован по цене
    перевозчика рейса, manual - вручную, migrated - перенесён из прежнего учёта (legacy_group_key
    - ключ группы строк прежнего учёта, уникален в компании). needs_review/review_reason - метка
    ручной проверки (например, расхождение с принятым счётом). requires_full_allocation:
    если истина, сумма распределений обязана равняться сумме расхода, иначе может быть меньше
    (нераспределённые общие расходы допустимы).
    """

    KINDS = [("carrier_transport", "Перевозчику за рейс"), ("other", "Прочий")]
    STATUSES = [("active", "Действует"), ("void", "Аннулирован")]
    SOURCES = [
        ("carrier_price_sync", "По цене перевозчика рейса"),
        ("manual", "Вручную"),
        ("migrated", "Перенесён из прежнего учёта"),
    ]
    REVIEW_REASONS = [
        ("invoice_variance", "Расхождение со счётом"),
        ("migrated_mismatch", "Расхождение при переносе"),
        ("manual", "Ручная проверка"),
    ]

    kind = models.CharField(max_length=20, choices=KINDS)
    title = models.CharField(max_length=255)
    category = models.ForeignKey(
        "core.HandbookValue",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника expense_category",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.ForeignKey("core.HandbookValue", on_delete=models.PROTECT, related_name="+")
    expense_date = models.DateField()
    status = models.CharField(max_length=8, choices=STATUSES, default="active")
    source = models.CharField(max_length=20, choices=SOURCES)
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="expenses"
    )
    carrier = models.ForeignKey(
        "forwarding.Carrier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="expenses",
    )
    legacy_group_key = models.CharField(max_length=255, blank=True)
    carrier_price_snapshot = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    needs_review = models.BooleanField(default=False)
    review_reason = models.CharField(max_length=24, choices=REVIEW_REASONS, blank=True)
    requires_full_allocation = models.BooleanField(default=False)
    voided_by = _user_fk()
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    created_by = _user_fk()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date", "-id"]
        indexes = [
            models.Index(fields=["company", "expense_date"], name="expense_company_date_idx"),
            models.Index(fields=["company", "trip"], name="expense_company_trip_idx"),
            models.Index(fields=["company", "status"], name="expense_company_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="expense_amount_gte_0"),
            models.CheckConstraint(
                condition=~Q(kind="carrier_transport")
                | (Q(trip__isnull=False) & Q(carrier__isnull=False)),
                name="expense_carrier_transport_trip_carrier",
            ),
            models.UniqueConstraint(
                fields=["trip"],
                condition=Q(kind="carrier_transport", status="active"),
                name="expense_one_active_carrier_per_trip",
            ),
            models.UniqueConstraint(
                fields=["company", "legacy_group_key"],
                condition=~Q(legacy_group_key=""),
                name="expense_company_legacy_group_uniq",
            ),
            models.CheckConstraint(
                condition=~Q(fx_rate_source="legacy_missing") | Q(base_amount__isnull=True),
                name="expense_legacy_missing_no_base",
            ),
        ]

    def __str__(self):
        return f"Расход #{self.pk} {self.kind} {self.amount}"


class ExpenseAllocation(TenantModel):
    """Доля расхода, отнесённая на заказ и/или рейс.

    Правило расширения (этап 2): одна доля - один срез анализа, и каждая доля учитывается ровно
    один раз. Техника, водитель и центр затрат добавятся nullable-колонками этой же таблицы;
    сумма долей одного расхода не превышает сумму расхода (проверяет сервис, а при
    requires_full_allocation она обязана равняться ей). Сейчас колонок для них нет намеренно.
    legacy_line связывает долю со строкой OrderService при переносе.
    """

    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name="allocations")
    order = models.ForeignKey(
        "forwarding.Order",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="expense_allocations",
    )
    trip = models.ForeignKey(
        "forwarding.Trip",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="expense_allocations",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    legacy_line = models.OneToOneField(
        "forwarding.OrderService",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="finance_allocation",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["company", "order"], name="expalloc_company_order_idx"),
            models.Index(fields=["company", "trip"], name="expalloc_company_trip_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="expalloc_amount_gt_0"),
            models.CheckConstraint(
                condition=Q(order__isnull=False) | Q(trip__isnull=False),
                name="expalloc_order_or_trip",
            ),
        ]


class ExpenseInvoiceAllocation(TenantModel):
    """Связь расхода с позицией принятого входящего счёта (часть суммы, покрытая счётом).

    released_at/release_reason фиксируют снятие связи (например, при отмене счёта); запись не
    удаляется, чтобы сохранялась история.
    """

    expense = models.ForeignKey(
        Expense, on_delete=models.PROTECT, related_name="invoice_allocations"
    )
    invoice_item = models.ForeignKey(
        "finance.InvoiceItem", on_delete=models.PROTECT, related_name="expense_allocations"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(max_length=255, blank=True)
    created_by = _user_fk()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["expense", "released_at"], name="expinvalloc_exp_released_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["expense", "invoice_item"], name="expinvalloc_expense_item_uniq"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="expinvalloc_amount_gt_0"),
        ]


class FinanceMigrationRun(TenantModel):
    """Запуск переноса, сверки или shadow-проверки (журнал; логика - в сервисах следующих задач)."""

    KINDS = [("migrate", "Перенос"), ("reconcile", "Сверка"), ("shadow_check", "Проверка shadow")]
    MODES = [("dry_run", "Пробный"), ("apply", "Применение")]
    STATUSES = [
        ("running", "Выполняется"),
        ("success", "Успешно"),
        ("failed", "Ошибка"),
        ("needs_review", "Требует проверки"),
    ]

    kind = models.CharField(max_length=16, choices=KINDS)
    mode = models.CharField(max_length=8, choices=MODES)
    status = models.CharField(max_length=14, choices=STATUSES, default="running")
    started_by = _user_fk()
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    params = models.JSONField(default=dict, blank=True)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["company", "kind", "-started_at"], name="finrun_cmp_kind_idx")
        ]


class FinanceMigrationIssue(TenantModel):
    """Замечание переноса/сверки/shadow, требующее внимания или ручного решения.

    Таблица допускает запись вне транзакции отката основной операции (это обеспечивает сервисный
    слой): замечание не должно пропасть вместе с откатом неудачной shadow-записи. run может быть
    пустым (замечание вне запуска); удаление запуска запрещено (PROTECT).
    """

    SEVERITIES = [("info", "Информация"), ("warning", "Предупреждение"), ("error", "Ошибка")]
    STATUSES = [("open", "Открыто"), ("resolved", "Решено")]

    run = models.ForeignKey(
        FinanceMigrationRun,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="issues",
    )
    issue_type = models.CharField(max_length=64)
    severity = models.CharField(max_length=8, choices=SEVERITIES, default="warning")
    source_model = models.CharField(max_length=64, blank=True)
    source_id = models.BigIntegerField(null=True, blank=True)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=8, choices=STATUSES, default="open")
    resolved_by = _user_fk()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(
                fields=["company", "status", "issue_type"], name="finissue_cmp_st_type_idx"
            ),
            models.Index(
                fields=["company", "source_model", "source_id"], name="finissue_source_idx"
            ),
        ]
