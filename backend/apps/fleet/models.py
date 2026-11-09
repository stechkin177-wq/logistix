"""Автопарк (модуль fleet): техника, её документы и страховки.

Модуль независим от forwarding и drivers. Назначение техники на рейс - необязательная ссылка
``Trip.vehicle`` (подзадача 2.3); прежнее текстовое поле ``Trip.vehicle_plate`` сохраняется.
Деньги (стоимость обслуживания, страховые премии) в этой подзадаче не хранятся: затраты по
технике позже идут через Expense/ExpenseAllocation (G1), параллельной финансовой системы нет.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TenantModel


class Vehicle(TenantModel, SoftDeleteModel):
    TRACTOR = "tractor"
    TRAILER = "trailer"
    TRUCK = "truck"
    OTHER = "other"
    KINDS = [
        (TRACTOR, "Тягач"),
        (TRAILER, "Полуприцеп/прицеп"),
        (TRUCK, "Грузовик"),
        (OTHER, "Другое"),
    ]
    ACTIVE = "active"
    REPAIR = "repair"
    INACTIVE = "inactive"
    STATUSES = [(ACTIVE, "В работе"), (REPAIR, "В ремонте"), (INACTIVE, "Выведен")]

    audit_masked_fields = ("vin", "notes")

    kind = models.CharField(max_length=16, choices=KINDS, default=TRUCK)
    plate = models.CharField(max_length=32)
    vin = models.CharField(max_length=32, blank=True)
    make = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    body_type = models.CharField(max_length=64, blank=True)
    capacity_kg = models.PositiveIntegerField(null=True, blank=True)
    volume_m3 = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=ACTIVE)
    # «Сверять пробег по GPS»: только показывает расхождение, официальный пробег не меняет.
    # Независимо от подключения GPS для отслеживания местоположения.
    gps_check = models.BooleanField(default=False)
    # Начальный пробег при подключении техники к системе: отдельное значение, не запись истории.
    # Официальный пробег затем формируется только показаниями рейсов (выезд и завершение).
    initial_odometer_km = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["company", "plate"], name="vehicle_company_plate_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "plate"],
                condition=Q(deleted_at__isnull=True),
                name="vehicle_company_plate_uniq",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["tractor", "trailer", "truck", "other"]),
                name="vehicle_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "repair", "inactive"]),
                name="vehicle_status_valid",
            ),
        ]

    def __str__(self):
        return self.plate


class _Dated(TenantModel):
    """Общее для документов и страховок техники: срок действия не раньше даты выдачи."""

    class Meta:
        abstract = True

    @staticmethod
    def dates_constraint(name):
        return models.CheckConstraint(
            condition=Q(starts_at__isnull=True)
            | Q(expires_at__isnull=True)
            | Q(expires_at__gte=models.F("starts_at")),
            name=name,
        )


class VehicleDocument(_Dated):
    REGISTRATION = "registration"
    INSPECTION = "inspection"
    PERMIT = "permit"
    OTHER = "other"
    KINDS = [
        (REGISTRATION, "Техпаспорт"),
        (INSPECTION, "Техосмотр"),
        (PERMIT, "Разрешение"),
        (OTHER, "Другое"),
    ]

    audit_masked_fields = ("number", "notes")

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=16, choices=KINDS, default=OTHER)
    number = models.CharField(max_length=64, blank=True)
    starts_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["company", "vehicle"], name="vehdoc_company_vehicle_idx")]
        constraints = [
            _Dated.dates_constraint("vehdoc_expires_after_start"),
            models.CheckConstraint(
                condition=Q(kind__in=["registration", "inspection", "permit", "other"]),
                name="vehdoc_kind_valid",
            ),
        ]


class Insurance(_Dated):
    OSAGO = "osago"
    KASKO = "kasko"
    CARGO = "cargo"
    OTHER = "other"
    KINDS = [
        (OSAGO, "ОСАГО"),
        (KASKO, "КАСКО"),
        (CARGO, "Страхование груза"),
        (OTHER, "Другое"),
    ]

    audit_masked_fields = ("policy_number", "notes")

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="insurances")
    kind = models.CharField(max_length=16, choices=KINDS, default=OSAGO)
    policy_number = models.CharField(max_length=64, blank=True)
    insurer = models.CharField(max_length=255, blank=True)
    starts_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["company", "vehicle"], name="insur_company_vehicle_idx")]
        constraints = [
            _Dated.dates_constraint("insur_expires_after_start"),
            models.CheckConstraint(
                condition=Q(kind__in=["osago", "kasko", "cargo", "other"]),
                name="insur_kind_valid",
            ),
        ]


class MileageReading(TenantModel):
    """ОФИЦИАЛЬНЫЙ пробег единицы техники (тягач и полуприцеп учитываются раздельно).

    Фиксируется только при выезде в рейс (``trip_start``) и после его завершения по отчёту
    водителя (``trip_end``). Пробег, указанный в заправках, обслуживании, страховках и других
    записях, - справочная информация и сюда не попадает. GPS показания не создаёт и не меняет.
    Произвольных ручных записей нет; начальный пробег - ``Vehicle.initial_odometer_km``.
    Показания не убывают во времени.
    """

    TRIP_START = "trip_start"
    TRIP_END = "trip_end"
    SOURCES = [(TRIP_START, "Выезд в рейс"), (TRIP_END, "Завершение рейса")]

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="mileage")
    # рейс-источник; рейс не удаляется физически (корзина), SET_NULL - на случай жёсткой очистки
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    recorded_at = models.DateTimeField()
    odometer_km = models.PositiveIntegerField()
    source = models.CharField(max_length=10, choices=SOURCES, default=TRIP_START)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["recorded_at", "id"]
        indexes = [
            models.Index(fields=["company", "vehicle", "recorded_at"], name="mileage_veh_time_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(source__in=["trip_start", "trip_end"]),
                name="mileage_source_valid",
            ),
            models.UniqueConstraint(
                fields=["trip", "vehicle", "source"],
                condition=Q(trip__isnull=False),
                name="mileage_one_per_trip_vehicle_phase",
            ),
        ]


class FleetSettings(TenantModel):
    """Настройки автопарка компании (одна запись на компанию)."""

    # допустимое расхождение официального пробега и GPS, км; больше - предупреждение
    gps_mismatch_km = models.PositiveIntegerField(default=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company"], name="fleetsettings_company_uniq"),
        ]


class ServiceRecord(TenantModel):
    """Обслуживание и ремонт: плановое ТО, выполненные работы, замена расходников.

    Деньги здесь НЕ хранятся: стоимость работ и запчастей учитывается только в Finance G1,
    запись лишь ссылается на расход (``expense``). Несколько записей могут ссылаться на один
    расход (например, акт на несколько работ) - сумма живёт в одном месте, двойного учёта нет.
    """

    MAINTENANCE = "maintenance"
    REPAIR = "repair"
    TIRES = "tires"
    OIL = "oil"
    FILTERS = "filters"
    INSPECTION = "inspection"
    OTHER = "other"
    KINDS = [
        (MAINTENANCE, "Плановое ТО"),
        (REPAIR, "Ремонт"),
        (TIRES, "Шины"),
        (OIL, "Масло"),
        (FILTERS, "Фильтры"),
        (INSPECTION, "Осмотр"),
        (OTHER, "Другое"),
    ]
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
    STATUSES = [
        (PLANNED, "Запланировано"),
        (IN_PROGRESS, "В работе"),
        (DONE, "Выполнено"),
        (CANCELLED, "Отменено"),
    ]

    audit_masked_fields = ("description",)

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="services")
    kind = models.CharField(max_length=16, choices=KINDS, default=MAINTENANCE)
    status = models.CharField(max_length=16, choices=STATUSES, default=PLANNED)
    title = models.CharField(max_length=255)
    planned_date = models.DateField(null=True, blank=True)
    done_date = models.DateField(null=True, blank=True)
    odometer_km = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)  # выполненные работы, замененные детали
    # напоминание о следующем таком же обслуживании
    next_due_date = models.DateField(null=True, blank=True)
    next_due_km = models.PositiveIntegerField(null=True, blank=True)
    expense = models.ForeignKey(
        "finance.Expense", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["company", "vehicle", "status"], name="service_veh_st_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    kind__in=[
                        "maintenance",
                        "repair",
                        "tires",
                        "oil",
                        "filters",
                        "inspection",
                        "other",
                    ]
                ),
                name="service_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["planned", "in_progress", "done", "cancelled"]),
                name="service_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(status="done") | Q(done_date__isnull=False),
                name="service_done_has_date",
            ),
        ]


class FuelFill(TenantModel):
    """Заправка: литры, дата, пробег. Стоимость - только в Finance G1 (ссылка ``expense``)."""

    DIESEL = "diesel"
    PETROL = "petrol"
    GAS = "gas"
    OTHER = "other"
    FUELS = [(DIESEL, "Дизель"), (PETROL, "Бензин"), (GAS, "Газ"), (OTHER, "Другое")]

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="fuel_fills")
    filled_at = models.DateTimeField()
    liters = models.DecimalField(max_digits=8, decimal_places=2)
    odometer_km = models.PositiveIntegerField(null=True, blank=True)
    full_tank = models.BooleanField(default=True)
    fuel_type = models.CharField(max_length=8, choices=FUELS, default=DIESEL)
    station = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=255, blank=True)
    expense = models.ForeignKey(
        "finance.Expense", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["filled_at", "id"]
        indexes = [
            models.Index(fields=["company", "vehicle", "filled_at"], name="fuel_veh_time_idx")
        ]
        constraints = [
            models.CheckConstraint(condition=Q(liters__gt=0), name="fuel_liters_gt_0"),
            models.CheckConstraint(
                condition=Q(fuel_type__in=["diesel", "petrol", "gas", "other"]),
                name="fuel_type_valid",
            ),
        ]
