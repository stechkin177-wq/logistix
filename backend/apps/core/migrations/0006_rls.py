"""RLS (политика tenant_isolation) на всех таблицах TenantModel приложения core."""

from django.db import migrations

from apps.core.rls import EnableRLS


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_auditlog"),
    ]

    operations = [
        EnableRLS("core.LegalEntity"),
        EnableRLS("core.Department"),
        EnableRLS("core.Role"),
        EnableRLS("core.Handbook"),
        EnableRLS("core.HandbookValue"),
        EnableRLS("core.NumberingRule"),
        EnableRLS("core.AuditLog"),
    ]
