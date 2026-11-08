"""Этап 1.5-B1: уникальность (consignment, seq) и seq >= 1 - после заполнения seq (0009)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("forwarding", "0009_stops_backfill")]

    operations = [
        migrations.AlterField(
            model_name="consignmentpoint",
            name="seq",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddConstraint(
            model_name="consignmentpoint",
            constraint=models.UniqueConstraint(
                fields=("consignment", "seq"), name="point_consignment_seq_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="consignmentpoint",
            constraint=models.CheckConstraint(
                condition=models.Q(("seq__gte", 1)), name="point_seq_gte_1"
            ),
        ),
    ]
