"""Ручное сопоставление статусов и completed_status (1.4.10)."""

import pytest

from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.handbooks.system_codes import SystemValueProtected, system_values_maintenance
from apps.core.tenancy import tenant_context
from apps.finance import status_mapping as sm
from apps.finance.errors import FinanceError
from apps.finance.models import CompanyFinancialSettings
from apps.finance.tests.helpers import first_user

pytestmark = pytest.mark.django_db


def code(exc):
    return exc.value.detail.code


def value(company, **kw):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code="trip_status", **kw)


def unmap(company, old_code="COMPLETED", new_name="Доставлен"):
    """Имитация компании с неоднозначным статусом: код снят, значение переименовано."""
    v = value(company, code=old_code)
    with tenant_context(company.id), system_values_maintenance():
        HandbookValue.all_objects.filter(pk=v.pk).update(code="", name=new_name)
        if old_code == "COMPLETED":
            CompanyFinancialSettings.all_objects.filter(company=company).update(
                completed_status=None
            )
    return HandbookValue.all_objects.get(pk=v.pk)


def settings_of(company):
    return CompanyFinancialSettings.all_objects.get(company=company)


def test_fresh_company_is_not_blocked(company):
    rep = sm.status_mapping_report(company)
    assert rep["switch_blocked"] is False and rep["unmapped_system_codes"] == []
    assert rep["completed_status"]["code"] == "COMPLETED"
    assert len(rep["values"]) == 6


def test_renamed_status_is_mapped_and_completed_status_follows(company):
    v = unmap(company)
    rep = sm.status_mapping_report(company)
    assert rep["switch_blocked"] is True
    assert rep["unmapped_system_codes"] == ["COMPLETED"]
    reasons = {b["code"] for b in rep["blockers"]}
    assert {"unmapped_system_codes", "completed_status_missing"} <= reasons
    cands = rep["unmapped"][0]["candidates"]
    assert v.pk in {c["id"] for c in cands}  # кандидат по признаку is_final
    user = first_user(company)
    sm.map_system_status(company, v, "COMPLETED", user=user)
    assert value(company, pk=v.pk).code == "COMPLETED"
    assert settings_of(company).completed_status_id == v.pk
    assert sm.status_mapping_report(company)["switch_blocked"] is False
    with tenant_context(company.id):
        entries = AuditLog.objects.filter(changes__source="finance.map_system_status")
        assert entries.count() == 2  # значение (код) и настройки (completed_status)


def test_idempotent_repeat_adds_no_audit(company):
    v = unmap(company)
    user = first_user(company)
    sm.map_system_status(company, v.pk, "COMPLETED", user=user)
    sm.map_system_status(company, v.pk, "COMPLETED", user=user)
    with tenant_context(company.id):
        assert AuditLog.objects.filter(changes__source="finance.map_system_status").count() == 2
        # повтор ничего не добавил: 2 записи от первого вызова (значение + настройки)
    assert value(company, pk=v.pk).code == "COMPLETED"


def test_code_taken_and_value_with_other_code(company):
    v = unmap(company, "UNLOADING", "Разгрузка")
    other = value(company, code="CANCELLED")
    user = first_user(company)
    with pytest.raises(FinanceError) as exc:
        sm.map_system_status(company, other, "UNLOADING", user=user)  # у значения уже CANCELLED
    assert code(exc) == "status_already_coded" and exc.value.status_code == 409
    free = value(company, pk=v.pk)
    with pytest.raises(FinanceError) as exc:
        sm.map_system_status(company, free, "CANCELLED", user=user)  # код CANCELLED занят
    assert code(exc) == "status_code_taken"
    assert value(company, pk=v.pk).code == ""


def test_unknown_code_and_inactive_value(company):
    v = unmap(company)
    user = first_user(company)
    with pytest.raises(FinanceError) as exc:
        sm.map_system_status(company, v, "DONE", user=user)
    assert code(exc) == "status_code_unknown"
    with tenant_context(company.id):
        HandbookValue.objects.filter(pk=v.pk).update(is_active=False)
    with pytest.raises(FinanceError) as exc:
        sm.map_system_status(company, v, "COMPLETED", user=user)
    assert code(exc) == "status_inactive"


def test_foreign_company_value_not_found(company, make_company):
    other, *_ = make_company()
    foreign = unmap(other)
    with pytest.raises(FinanceError) as exc:
        sm.map_system_status(company, foreign, "COMPLETED", user=first_user(company))
    assert code(exc) == "status_not_found" and exc.value.status_code == 404
    assert value(other, pk=foreign.pk).code == ""
    assert settings_of(other).completed_status_id is None


def test_not_trip_status_value_rejected(company):
    with tenant_context(company.id):
        cur = HandbookValue.objects.filter(handbook__code="currency").first()
    with pytest.raises(FinanceError) as exc:
        sm.map_system_status(company, cur, "COMPLETED", user=first_user(company))
    assert code(exc) == "status_not_found"
    with pytest.raises(FinanceError) as exc:
        sm.map_system_status(company, "x", "COMPLETED", user=first_user(company))
    assert code(exc) == "status_invalid"


def test_direct_code_change_still_protected(company):
    """Защита 1.1 не ослаблена: вне сервиса код присвоить нельзя."""
    v = unmap(company)
    with tenant_context(company.id):
        v = HandbookValue.objects.get(pk=v.pk)
        v.code = "COMPLETED"
        with pytest.raises(SystemValueProtected):
            v.save()


def test_other_code_than_completed_keeps_completed_status(company):
    before = settings_of(company).completed_status_id
    v = unmap(company, "UNLOADING", "Разгрузка")
    sm.map_system_status(company, v, "UNLOADING", user=first_user(company))
    assert settings_of(company).completed_status_id == before


def test_completed_status_must_point_to_completed_code(company):
    cancelled = value(company, code="CANCELLED")
    CompanyFinancialSettings.all_objects.filter(company=company).update(completed_status=cancelled)
    rep = sm.status_mapping_report(company)
    assert rep["switch_blocked"] is True
    assert [b["code"] for b in rep["blockers"]] == ["completed_status_not_completed"]


def test_one_value_per_code_check(company):
    assert sm.duplicate_codes(company) == []
