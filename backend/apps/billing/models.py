from django.db import models


class Plan(models.Model):
    """Тариф. Цены намеренно не хранятся (задаются вне кода). Лимиты: null = без ограничений."""

    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"
    BILLING_TYPES = [(MONTHLY, "Помесячно"), (YEARLY, "Ежегодно"), (LIFETIME, "Бессрочно")]

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    billing_type = models.CharField(max_length=16, choices=BILLING_TYPES)
    limits = models.JSONField(default=dict, blank=True)
    modules = models.JSONField(default=list, blank=True)
    options = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]

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
