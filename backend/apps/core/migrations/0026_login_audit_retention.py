"""Журнал входов: действие login_failed и настройки срока хранения (CompanyAuditSettings, под RLS)."""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

from apps.core.rls import EnableRLS


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0025_totp_and_token_revocation"),
    ]

    operations = [

        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("create", "Создание"),
                    ("update", "Изменение"),
                    ("delete", "Удаление"),
                    ("restore", "Восстановление"),
                    ("login", "Вход"),
                    ("login_failed", "Неудачный вход"),
                ],
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="CompanyAuditSettings",
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
                    "login_audit_retention_days",
                    models.PositiveSmallIntegerField(
                        default=90,
                        help_text="Сколько дней хранятся события входа в журнале аудита (по умолчанию 3 месяца)",
                        validators=[
                            django.core.validators.MinValueValidator(30),
                            django.core.validators.MaxValueValidator(1095),
                        ],
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.company",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("company",), name="companyauditsettings_company_uniq"
                    )
                ],
            },
        ),
        EnableRLS("core.CompanyAuditSettings"),
    ]
