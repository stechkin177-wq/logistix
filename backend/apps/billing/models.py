from django.db import models


class Plan(models.Model):
    """Тариф. Всё содержимое (название, цена, валюта, период, порядок, модули, лимиты) хранится
    в данных и меняется администратором платформы без изменения кода; ни названия, ни число
    тарифов, ни их порядок в коде не зашиты.

    Состояние: черновик (``is_active`` = False, ``archived_at`` пусто) - не предлагается;
    активный (``is_active``) - предлагается для новых подписок; архивный (``archived_at``) - не
    предлагается, действующие подписки продолжают работать. ``is_default`` - тариф, который
    получают новые компании (не более одного). Лимиты: null = без ограничений.
    """

    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"
    BILLING_TYPES = [(MONTHLY, "Помесячно"), (YEARLY, "Ежегодно"), (LIFETIME, "Бессрочно")]

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"

    code = models.SlugField(unique=True)  # неизменяем после создания: на него ссылаются отчёты
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    billing_type = models.CharField(max_length=16, choices=BILLING_TYPES)
    price = models.DecimalField(max_digits=14, decimal_places=2, default=0)  # 0 - бесплатный
    currency = models.CharField(max_length=3, default="KZT")
    sort_order = models.PositiveIntegerField(default=0)
    # бесплатный период новой компании на этом тарифе, дней (0 - нет); задаёт администратор
    free_period_days = models.PositiveIntegerField(default=0)
    # с какого процента использования лимита предупреждать владельца (0 - не предупреждать заранее)
    limit_warn_percent = models.PositiveSmallIntegerField(default=80)
    limits = models.JSONField(default=dict, blank=True)
    modules = models.JSONField(default=list, blank=True)
    # функции внутри модулей {код: True | уровень}; каталог - apps/billing/features.py
    features = models.JSONField(default=dict, blank=True)
    options = models.JSONField(default=dict, blank=True)  # служебные метки миграций
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gte=0), name="plan_price_gte_0"),
            models.CheckConstraint(
                condition=models.Q(limit_warn_percent__lte=100), name="plan_warn_percent_lte_100"
            ),
            models.CheckConstraint(
                condition=models.Q(archived_at__isnull=True) | models.Q(is_active=False),
                name="plan_archived_not_active",
            ),
            models.CheckConstraint(
                condition=models.Q(is_default=False)
                | (models.Q(is_active=True) & models.Q(archived_at__isnull=True)),
                name="plan_default_must_be_active",
            ),
            models.UniqueConstraint(
                fields=["is_default"], condition=models.Q(is_default=True), name="plan_one_default"
            ),
        ]

    @property
    def status(self) -> str:
        if self.archived_at is not None:
            return self.ARCHIVED
        return self.ACTIVE if self.is_active else self.DRAFT

    def __str__(self):
        return self.code


class Subscription(models.Model):
    """Подписка компании. Сохранённый status - ручная отметка; фактический статус
    считает billing.services.effective_status по датам."""

    TRIAL = "trial"
    ACTIVE = "active"
    GRACE = "grace"
    READONLY = "readonly"
    BLOCKED = "blocked"
    STATUSES = [
        (TRIAL, "Пробный"),
        (ACTIVE, "Активна"),
        (GRACE, "Льготный период"),
        (READONLY, "Только чтение"),
        (BLOCKED, "Заблокирована"),
    ]

    company = models.OneToOneField(
        "core.Company", on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=16, choices=STATUSES, default=ACTIVE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    is_free_period = models.BooleanField(default=False)
    def __str__(self):
        return f"{self.company_id}:{self.plan_id}:{self.status}"


class SubscriptionPeriod(models.Model):
    """Неизменяемая запись об оплаченном (или бесплатном) периоде подписки.

    Цена и валюта периода фиксируются в момент его начала: последующее изменение цены тарифа
    записанные периоды не трогает; новая цена применяется только к новым периодам (продление,
    смена тарифа с новым периодом). Платежей нет: подтверждение оплаты вне системы.
    """

    START = "start"
    RENEWAL = "renewal"
    PLAN_CHANGE = "plan_change"
    REASONS = [(START, "Начало"), (RENEWAL, "Продление"), (PLAN_CHANGE, "Смена тарифа")]

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="periods")
    plan_code = models.CharField(max_length=50)  # тариф на момент периода (снимок)
    reason = models.CharField(max_length=16, choices=REASONS)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)  # null - бессрочный
    price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="KZT")
    is_free = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gte=0), name="period_price_gte_0"),
        ]


class BillingEvent(models.Model):
    """Журнал изменений тарифов и подписок компаний (платформенный, без привязки к компании).

    Пишется при каждом изменении администратором платформы: что изменено ({поле: [было, стало]}),
    кем и когда. Записи не редактируются и не удаляются.
    """

    PLAN = "plan"
    SUBSCRIPTION = "subscription"
    KINDS = [(PLAN, "Тариф"), (SUBSCRIPTION, "Подписка компании")]

    kind = models.CharField(max_length=16, choices=KINDS)
    key = models.CharField(max_length=64)  # код тарифа или id компании
    action = models.CharField(max_length=40)
    changes = models.JSONField(default=dict, blank=True)
    user = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor = models.CharField(max_length=255, blank=True)  # снимок email на момент действия
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["kind", "key"], name="billingevent_kind_key_idx")]
