"""Срок хранения событий входа компании (CompanyAuditSettings; нет строки - 90 дней)."""

from apps.core.models import DEFAULT_LOGIN_AUDIT_RETENTION_DAYS, CompanyAuditSettings


def login_retention_days() -> int:
    """Срок текущей компании (контекст компании должен быть задан)."""
    row = CompanyAuditSettings.objects.first()
    return row.login_audit_retention_days if row else DEFAULT_LOGIN_AUDIT_RETENTION_DAYS


def set_login_retention_days(days: int) -> int:
    row = CompanyAuditSettings.objects.first()
    if row is None:
        CompanyAuditSettings(login_audit_retention_days=days).save()
    elif row.login_audit_retention_days != days:
        row.login_audit_retention_days = days
        row.save(update_fields=["login_audit_retention_days"])
    return days
