"""Trip.completed_at и индекс (company, completed_at): только схема, без данных."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("forwarding", "0006_trip_carrier_price"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="trip",
            name="completed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddIndex(
            model_name="trip",
            index=models.Index(
                fields=["company", "completed_at"], name="trip_company_completed_idx"
            ),
        ),
    ]
