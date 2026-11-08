"""Этап 1.5-C1: TripConsignment -> участок перевозки (схема, аддитивно).

Добавляет from_stop/to_stop (FK на остановку, PROTECT), leg_seq, status, доли
(weight_kg/volume_m3/pallets). Старая уникальность (рейс, груз) заменена: (рейс, груз,
from_stop, to_stop) для заполненных пар и частичная уникальность (рейс, груз) для записей без
остановок (NULL в PostgreSQL различны); CHECK «обе остановки заданы или обе пусты». Данные
заполняет 0012. Самодостаточна (код приложения не импортируется). Откат допустим, пока в БД
нет двух участков одного груза в одном рейсе (иначе прежняя уникальность не восстановится):
в этом случае останавливается с понятной ошибкой, ничего не удаляя.
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def _set_company(connection, company_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def guard_reverse(apps, schema_editor):
    connection = schema_editor.connection
    Company = apps.get_model("core", "Company")
    problems = 0
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM (SELECT 1 FROM forwarding_tripconsignment "
                    "WHERE company_id = %s GROUP BY trip_id, consignment_id HAVING count(*) > 1) d",
                    [company.id],
                )
                problems += cursor.fetchone()[0]
    finally:
        _set_company(connection, None)
    if problems:
        raise RuntimeError(
            "Откат forwarding.0011 невозможен: в БД есть грузы с несколькими участками в одном "
            f"рейсе: {problems}. Данные не удалены; оставьте по одному участку груза в рейсе."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("forwarding", "0010_stops_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="tripconsignment",
            name="from_stop",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="legs_from",
                to="forwarding.consignmentpoint",
            ),
        ),
        migrations.AddField(
            model_name="tripconsignment",
            name="to_stop",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="legs_to",
                to="forwarding.consignmentpoint",
            ),
        ),
        migrations.AddField(
            model_name="tripconsignment",
            name="leg_seq",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="tripconsignment",
            name="status",
            field=models.CharField(
                choices=[
                    ("planned", "Запланирован"),
                    ("in_progress", "В пути"),
                    ("done", "Выполнен"),
                    ("cancelled", "Отменён"),
                ],
                default="planned",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="tripconsignment",
            name="weight_kg",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name="tripconsignment",
            name="volume_m3",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name="tripconsignment",
            name="pallets",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="tripconsignment",
            constraint=models.UniqueConstraint(
                fields=("trip", "consignment", "from_stop", "to_stop"),
                name="tripcons_trip_cons_leg_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="tripconsignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("from_stop__isnull", True), ("to_stop__isnull", True)),
                fields=("trip", "consignment"),
                name="tripcons_trip_cons_whole_uniq",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="tripconsignment", name="tripcons_trip_cons_uniq"
        ),
        migrations.AddConstraint(
            model_name="tripconsignment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("from_stop__isnull", True), ("to_stop__isnull", True)),
                    models.Q(("from_stop__isnull", False), ("to_stop__isnull", False)),
                    _connector="OR",
                ),
                name="tripcons_stops_both_or_none",
            ),
        ),
        migrations.AddConstraint(
            model_name="tripconsignment",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["planned", "in_progress", "done", "cancelled"])),
                name="tripcons_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="tripconsignment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("weight_kg__isnull", True), ("weight_kg__gte", 0), _connector="OR"),
                    models.Q(("volume_m3__isnull", True), ("volume_m3__gte", 0), _connector="OR"),
                ),
                name="tripcons_share_gte_0",
            ),
        ),
        # последней: при откате выполняется первой (до восстановления прежней уникальности)
        migrations.RunPython(migrations.RunPython.noop, guard_reverse),
    ]
