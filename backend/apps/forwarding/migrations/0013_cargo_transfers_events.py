"""Этап 1.5-D1: Consignment.current_stop/location_status, CargoTransfer, ConsignmentEvent (RLS).

Аддитивная, обратимая, самодостаточная миграция (код приложения не импортируется)."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from apps.core.rls import EnableRLS


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_rls"),
        ("forwarding", "0012_tripconsignment_legs_backfill"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CargoTransfer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "transfer_kind",
                    models.CharField(
                        choices=[
                            ("to_carrier", "Другому перевозчику"),
                            ("between_vehicles", "Перегрузка между ТС"),
                            ("to_storage", "На склад"),
                            ("from_storage", "Со склада"),
                        ],
                        max_length=16,
                    ),
                ),
                ("carrier_changed", models.BooleanField(default=False)),
                ("transferred_at", models.DateTimeField()),
                (
                    "weight_kg",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "volume_m3",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("pallets", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("initiated", "Инициирована"),
                            ("confirmed", "Подтверждена"),
                            ("reversed", "Сторно"),
                        ],
                        default="initiated",
                        max_length=12,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("manual", "Вручную"),
                            ("driver_app", "Приложение водителя"),
                        ],
                        default="manual",
                        max_length=12,
                    ),
                ),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-transferred_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ConsignmentEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("arrived", "Прибыл на остановку"),
                            ("loaded", "Погружен"),
                            ("departed", "Отправлен с остановки"),
                            ("transferred", "Передан"),
                            ("unloaded", "Выгружен"),
                            ("delivered", "Доставлен"),
                            ("skipped", "Остановка пропущена"),
                            ("stored", "Помещён на хранение"),
                        ],
                        max_length=12,
                    ),
                ),
                ("occurred_at", models.DateTimeField()),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("manual", "Вручную"),
                            ("driver_app", "Приложение водителя"),
                        ],
                        default="manual",
                        max_length=12,
                    ),
                ),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["occurred_at", "id"],
            },
        ),
        migrations.AddField(
            model_name="consignment",
            name="current_stop",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="forwarding.consignmentpoint",
            ),
        ),
        migrations.AddField(
            model_name="consignment",
            name="location_status",
            field=models.CharField(
                choices=[
                    ("planned", "Запланирован"),
                    ("in_transit", "В пути"),
                    ("at_stop", "На остановке"),
                    ("in_storage", "На хранении"),
                    ("delivered", "Доставлен"),
                ],
                default="planned",
                max_length=12,
            ),
        ),
        migrations.AddIndex(
            model_name="consignment",
            index=models.Index(
                fields=["company", "location_status"], name="consignment_location_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="consignment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "location_status__in",
                        ["planned", "in_transit", "at_stop", "in_storage", "delivered"],
                    )
                ),
                name="consignment_location_valid",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="core.company",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="confirmed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="consignment",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="transfers",
                to="forwarding.consignment",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="from_carrier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="forwarding.carrier",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="from_stop",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="transfers_from",
                to="forwarding.consignmentpoint",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="from_trip",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="forwarding.trip",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="initiated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="reverses",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reversals",
                to="forwarding.cargotransfer",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="to_carrier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="forwarding.carrier",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="to_stop",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="transfers_to",
                to="forwarding.consignmentpoint",
            ),
        ),
        migrations.AddField(
            model_name="cargotransfer",
            name="to_trip",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="forwarding.trip",
            ),
        ),
        migrations.AddField(
            model_name="consignmentevent",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="core.company",
            ),
        ),
        migrations.AddField(
            model_name="consignmentevent",
            name="consignment",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="forwarding.consignment",
            ),
        ),
        migrations.AddField(
            model_name="consignmentevent",
            name="leg",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="events",
                to="forwarding.tripconsignment",
            ),
        ),
        migrations.AddField(
            model_name="consignmentevent",
            name="recorded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="consignmentevent",
            name="stop",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="forwarding.consignmentpoint",
            ),
        ),
        migrations.AddField(
            model_name="consignmentevent",
            name="trip",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="forwarding.trip",
            ),
        ),
        migrations.AddIndex(
            model_name="cargotransfer",
            index=models.Index(fields=["company", "consignment"], name="transfer_company_cons_idx"),
        ),
        migrations.AddIndex(
            model_name="cargotransfer",
            index=models.Index(fields=["company", "status"], name="transfer_company_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="cargotransfer",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "transfer_kind__in",
                        [
                            "to_carrier",
                            "between_vehicles",
                            "to_storage",
                            "from_storage",
                        ],
                    )
                ),
                name="transfer_kind_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="cargotransfer",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["initiated", "confirmed", "reversed"])),
                name="transfer_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="cargotransfer",
            constraint=models.CheckConstraint(
                condition=models.Q(("source__in", ["manual", "driver_app"])),
                name="transfer_source_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="cargotransfer",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("weight_kg__isnull", True),
                        ("weight_kg__gte", 0),
                        _connector="OR",
                    ),
                    models.Q(
                        ("volume_m3__isnull", True),
                        ("volume_m3__gte", 0),
                        _connector="OR",
                    ),
                ),
                name="transfer_share_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="cargotransfer",
            constraint=models.UniqueConstraint(
                condition=models.Q(("reverses__isnull", False)),
                fields=("reverses",),
                name="transfer_one_reversal",
            ),
        ),
        migrations.AddIndex(
            model_name="consignmentevent",
            index=models.Index(
                fields=["company", "consignment", "occurred_at"],
                name="event_company_cons_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="consignmentevent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "event_type__in",
                        [
                            "arrived",
                            "loaded",
                            "departed",
                            "transferred",
                            "unloaded",
                            "delivered",
                            "skipped",
                            "stored",
                        ],
                    )
                ),
                name="event_type_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="consignmentevent",
            constraint=models.CheckConstraint(
                condition=models.Q(("source__in", ["manual", "driver_app"])),
                name="event_source_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="consignmentevent",
            constraint=models.UniqueConstraint(
                fields=("consignment", "stop", "event_type", "occurred_at"),
                name="event_idempotent_uniq",
            ),
        ),
        EnableRLS("forwarding.CargoTransfer"),
        EnableRLS("forwarding.ConsignmentEvent"),
    ]
