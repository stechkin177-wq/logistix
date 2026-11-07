"""Ручное сопоставление статусов рейса с системными кодами и completed_status (1.4.10).

Логика 1.1 ставит Trip.completed_at при переходе в статус с системным кодом COMPLETED, а признание
дохода (income.py) требует status == completed_status И completed_at. Поэтому completed_status
обязан указывать на значение с кодом COMPLETED: ручное сопоставление = назначение системного кода
значению статуса компании, а при коде COMPLETED completed_status выставляется автоматически.

Сервис НИЧЕГО не определяет сам: значение выбирает человек (finance.manage_settings); автоматических
догадок по названию нет, кандидаты в отчёте - только подсказка. Компания с несопоставленными
статусами не переключается на engine=new (switch_blockers используется условием переключения).
"""

from django.db import transaction

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.handbooks.services import unmapped_system_codes
from apps.core.handbooks.status_codes import TRIP_STATUS, analyze
from apps.core.handbooks.system_codes import (
    SYSTEM_CODES,
    system_code_assignment,
)
from apps.core.tenancy import tenant_context

from .errors import FinanceError
from .fx import get_settings
from .models import CompanyFinancialSettings

COMPLETED_CODE = "COMPLETED"


def _status_values(company):
    """Значения trip_status компании (в контексте компании)."""
    return HandbookValue.objects.filter(handbook__code=TRIP_STATUS).order_by("order", "id")


def _lookup_value(value):
    """Значение своей компании (объект или id) без блокировки; чужое не находится."""
    pk = value.pk if isinstance(value, HandbookValue) else value
    if isinstance(pk, bool) or not isinstance(pk, int):
        raise FinanceError("status_invalid", "Нужен идентификатор значения статуса рейса")
    return pk


def duplicate_codes(company) -> list[str]:
    """Системные коды, которые несёт более одного значения (в норме пусто: уникальность в БД)."""
    with tenant_context(company.id):
        counts: dict[str, int] = {}
        for code in _status_values(company).exclude(code="").values_list("code", flat=True):
            counts[code] = counts.get(code, 0) + 1
    return sorted(c for c, n in counts.items() if n > 1 and c in SYSTEM_CODES[TRIP_STATUS])


@transaction.atomic
def map_system_status(company, value, code: str, *, user) -> HandbookValue:
    """Назначает системный код значению статуса рейса компании (под защитой system_code_assignment).

    Значение должно быть активным, без кода и из справочника trip_status ЭТОЙ компании; код -
    из реестра trip_status и свободен. Повтор той же пары - без изменений. Другой код у значения
    или занятый код - отказ. Код COMPLETED автоматически становится completed_status компании.
    """
    code = (code or "").strip()
    if code not in SYSTEM_CODES[TRIP_STATUS]:
        raise FinanceError(
            "status_code_unknown",
            "Код не входит в реестр системных кодов статусов рейса: "
            + ", ".join(sorted(SYSTEM_CODES[TRIP_STATUS])),
        )
    pk = _lookup_value(value)
    with tenant_context(company.id):
        row = (
            HandbookValue.objects.select_related("handbook")
            .select_for_update(of=("self",))
            .filter(pk=pk, handbook__code=TRIP_STATUS)
            .first()
        )  # менеджер компании: чужое значение не находится
        if row is None:
            raise FinanceError(
                "status_not_found", "Значение статуса рейса не найдено", status_code=404
            )
        settings = get_settings(company)
        if row.code == code:
            pass  # идемпотентно
        else:
            if row.code:
                raise FinanceError(
                    "status_already_coded",
                    f"У значения «{row.name}» уже есть системный код {row.code}: менять его нельзя",
                    status_code=409,
                )
            if not row.is_active:
                raise FinanceError(
                    "status_inactive",
                    "Неактивному значению нельзя назначить системный код",
                    status_code=409,
                )
            holder = HandbookValue.objects.filter(handbook=row.handbook, code=code).first()
            if holder is not None:
                raise FinanceError(
                    "status_code_taken",
                    f"Код {code} уже назначен значению «{holder.name}»",
                    status_code=409,
                )
            with system_code_assignment():
                row.code = code
                row.save(update_fields=["code"])
            audit.log(
                "update",
                row,
                user,
                {"code": ["", code], "source": "finance.map_system_status"},
            )
        if code == COMPLETED_CODE and settings.completed_status_id != row.pk:
            settings = CompanyFinancialSettings.objects.select_for_update().get(
                company_id=company.id
            )
            old_id = settings.completed_status_id
            settings.completed_status = row
            settings.updated_by = user if getattr(user, "pk", None) else None
            settings.save()
            audit.log(
                "update",
                settings,
                user,
                {"completed_status_id": [old_id, row.pk], "source": "finance.map_system_status"},
            )
        return row


def switch_blockers(company) -> list[dict]:
    """Причины, по которым компанию нельзя переключать на engine=new (по статусам).

    [{'code': ..., 'message': ...}]; пусто - статусы сопоставлены.
    """
    out: list[dict] = []
    unmapped = unmapped_system_codes(company)
    if unmapped:
        out.append(
            {
                "code": "unmapped_system_codes",
                "message": "Не сопоставлены системные коды статусов рейса: " + ", ".join(unmapped),
            }
        )
    dupes = duplicate_codes(company)
    if dupes:
        out.append(
            {
                "code": "duplicate_system_codes",
                "message": "Системный код назначен нескольким значениям: " + ", ".join(dupes),
            }
        )
    settings = get_settings(company)
    with tenant_context(company.id):
        completed = settings.completed_status
        if completed is None:
            out.append(
                {
                    "code": "completed_status_missing",
                    "message": "Не задан completed_status (завершающий статус рейса)",
                }
            )
        elif completed.code != COMPLETED_CODE or not completed.is_active:
            out.append(
                {
                    "code": "completed_status_not_completed",
                    "message": "completed_status должен указывать на активное значение "
                    "с системным кодом COMPLETED",
                }
            )
    return out


def status_mapping_report(company) -> dict:
    """Отчёт для ручной проверки: значения, непривязанные коды, кандидаты, completed_status."""
    settings = get_settings(company)
    with tenant_context(company.id):
        rows = [
            {
                "id": v.pk,
                "name": v.name,
                "code": v.code,
                "is_active": v.is_active,
                "is_final": v.is_final,
                "is_initial": v.is_initial,
            }
            for v in _status_values(company)
        ]
        completed = settings.completed_status
    reports = analyze(TRIP_STATUS, SYSTEM_CODES[TRIP_STATUS], rows)
    unmapped = [
        {
            "code": r.code,
            "reason": r.reason,
            "candidates": [c for c in r.candidates if c["id"] in {x["id"] for x in rows}],
        }
        for r in reports
        if not r.assigned
    ]
    blockers = switch_blockers(company)
    return {
        "values": rows,
        "unmapped": unmapped,
        "unmapped_system_codes": [u["code"] for u in unmapped],
        "completed_status": (
            {"id": completed.pk, "name": completed.name, "code": completed.code}
            if completed is not None
            else None
        ),
        "switch_blocked": bool(blockers),
        "blockers": blockers,
    }
