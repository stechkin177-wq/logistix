"""Trip.price -> Trip.carrier_price: переименование только в состоянии Django.

Столбец БД `price` и ограничение `trip_price_gte_0` остаются как есть (db_column="price"),
поэтому на уровне БД миграция ничего не делает и обратима без потерь.
"""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forwarding", "0005_party_requisites"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveConstraint(model_name="trip", name="trip_price_gte_0"),
                migrations.RenameField(model_name="trip", old_name="price", new_name="carrier_price"),
                migrations.AlterField(
                    model_name="trip",
                    name="carrier_price",
                    field=models.DecimalField(
                        db_column="price",
                        decimal_places=2,
                        default=0,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                migrations.AddConstraint(
                    model_name="trip",
                    constraint=models.CheckConstraint(
                        condition=models.Q(("carrier_price__gte", 0)), name="trip_price_gte_0"
                    ),
                ),
            ],
        ),
    ]
