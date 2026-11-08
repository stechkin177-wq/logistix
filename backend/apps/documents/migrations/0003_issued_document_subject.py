"""Универсальный субъект документа: nullable subject_type/subject_id + индекс (A7).

Аддитивная и обратимая миграция; прежние поля client/order/trip/invoice не меняются.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0002_seed_starter_templates"),
    ]

    operations = [
        migrations.AddField(
            model_name="issueddocument",
            name="subject_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issueddocument",
            name="subject_type",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddIndex(
            model_name="issueddocument",
            index=models.Index(
                fields=["company", "subject_type", "subject_id"],
                name="issueddoc_subject_idx",
            ),
        ),
    ]
