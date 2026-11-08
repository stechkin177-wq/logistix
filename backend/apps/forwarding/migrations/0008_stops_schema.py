"""Этап 1.5-B1: ConsignmentPoint -> остановки маршрута (схема, аддитивно).

Добавляет seq, status, arrived_at, done_at, доли (weight_kg/volume_m3/pallets); расширяет виды
(load, unload, transit, transfer, customs); снимает уникальность (consignment, kind) и
прежний CHECK видов. Уникальность (consignment, seq) добавляет 0010 ПОСЛЕ заполнения seq (0009).
Самодостаточна (код приложения не импортируется). Откат допустим, пока в БД нет данных, которые
нельзя представить в прежней схеме (виды вне load/unload или повтор вида в грузе): иначе
останавливается с понятной ошибкой, ничего не удаляя.
"""

import django.core.validators
from django.db import migrations, models


def _set_company(connection, company_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def guard_reverse(apps, schema_editor):
    """Откат: прежняя схема не вмещает расширенные виды и повторы вида в одном грузе."""
    connection = schema_editor.connection
    Company = apps.get_model("core", "Company")
    problems = 0
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM forwarding_consignmentpoint "
                    "WHERE company_id = %s AND kind NOT IN ('load', 'unload')",
                    [company.id],
                )
                problems += cursor.fetchone()[0]
                cursor.execute(
                    "SELECT count(*) FROM (SELECT 1 FROM forwarding_consignmentpoint "
                    "WHERE company_id = %s GROUP BY consignment_id, kind HAVING count(*) > 1) d",
                    [company.id],
                )
                problems += cursor.fetchone()[0]
    finally:
        _set_company(connection, None)
    if problems:
        raise RuntimeError(
            "Откат forwarding.0008 невозможен: в БД есть остановки, которые прежняя схема не "
            f"вмещает (промежуточные/несколько погрузок или выгрузок): {problems}. "
            "Данные не удалены; приведите маршруты к виду «одна погрузка, одна выгрузка»."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_manage_modules_permission"),
        ("forwarding", "0007_trip_completed_at"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="consignmentpoint",
            options={"ordering": ["seq", "id"]},
        ),
        migrations.AddField(
            model_name="consignmentpoint",
            name="seq",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="consignmentpoint",
            name="status",
            field=models.CharField(
                choices=[
                    ("planned", "Запланирована"),
                    ("arrived", "Прибыли"),
                    ("done", "Выполнена"),
                    ("skipped", "Пропущена"),
                ],
                default="planned",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="consignmentpoint",
            name="arrived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="consignmentpoint",
            name="done_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="consignmentpoint",
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
            model_name="consignmentpoint",
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
            model_name="consignmentpoint",
            name="pallets",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="consignmentpoint",
            name="kind",
            field=models.CharField(
                choices=[
                    ("load", "Погрузка"),
                    ("unload", "Выгрузка"),
                    ("transit", "Промежуточная"),
                    ("transfer", "Передача/перегрузка"),
                    ("customs", "Граница/таможня"),
                ],
                max_length=8,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="consignmentpoint", name="point_consignment_kind_uniq"
        ),
        migrations.RemoveConstraint(model_name="consignmentpoint", name="point_kind_valid"),
        migrations.AddConstraint(
            model_name="consignmentpoint",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("kind__in", ["load", "unload", "transit", "transfer", "customs"])
                ),
                name="point_kind_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="consignmentpoint",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["planned", "arrived", "done", "skipped"])),
                name="point_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="consignmentpoint",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("weight_kg__isnull", True), ("weight_kg__gte", 0), _connector="OR"),
                    models.Q(("volume_m3__isnull", True), ("volume_m3__gte", 0), _connector="OR"),
                ),
                name="point_share_gte_0",
            ),
        ),
        migrations.AddIndex(
            model_name="consignmentpoint",
            index=models.Index(
                fields=["company", "consignment", "seq"], name="point_company_cons_seq_idx"
            ),
        ),
        # последней: при откате выполняется первой (до восстановления прежних ограничений)
        migrations.RunPython(migrations.RunPython.noop, guard_reverse),
    ]
