"""Таблицы тестовых моделей (подключаются только через config/settings_test.py).

Миграция нужна, чтобы таблицы создавались после core.Company: syncdb у
приложений без миграций в pytest-django идёт раньше миграций и падает на FK.
"""

import django.db.models.deletion
from django.db import migrations, models


def _company():
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.company"
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [("core", "0002_company_legalentity")]

    operations = [
        migrations.CreateModel(
            name="PlainTenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50)),
                ("company", _company()),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="SoftTenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("name", models.CharField(max_length=50)),
                ("company", _company()),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="SoftOnly",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("name", models.CharField(max_length=50)),
            ],
            options={"abstract": False},
        ),
    ]
