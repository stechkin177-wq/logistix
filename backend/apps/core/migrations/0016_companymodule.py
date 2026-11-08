"""Конфигурация модулей компании CompanyModule (tenant-таблица, RLS)."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from apps.core.rls import EnableRLS


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_module_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyModule",
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
                ("module_code", models.CharField(max_length=32)),
                ("enabled", models.BooleanField(default=True)),
                ("enabled_at", models.DateTimeField(blank=True, null=True)),
                ("disabled_at", models.DateTimeField(blank=True, null=True)),
                ("reason", models.TextField(blank=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.company",
                    ),
                ),
                (
                    "disabled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "enabled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("company", "module_code"),
                        name="companymodule_company_code_uniq",
                    )
                ],
            },
        ),
        EnableRLS("core.CompanyModule"),
    ]
