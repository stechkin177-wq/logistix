# ruff: noqa: E501
"""Переключение режима учёта компании, откат и «безопасная остановка» (1.4.11).

Переходы: legacy -> shadow (ничего не меняет в данных) и shadow -> new (все условия проверяются
кодом; отказ возвращает полный перечень причин). Откат new -> shadow|legacy разрешён только в
первые 30 дней и пока в новой модели нет записей, которых нет в старой; данные при откате НЕ
удаляются. Заморозка (financial_writes_frozen) останавливает все финансовые записи (423).

Сервисы НЕ запускаются против реальных компаний сами: это делают только управляющие команды по
явному решению заказчика (--approval-ref).
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.audit import services as audit
from apps.core.models import Company
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Order

from . import income as income_svc
from . import periods, reconcile, status_mapping
from .engine import local_date
from .errors import FinanceError
from .fx import fx_snapshot, get_settings
from .models import (
    CompanyFinancialSettings,
    Expense,
    ExpenseAllocation,
    ExpenseInvoiceAllocation,
    FinanceMigrationIssue,
    Income,
    IncomeTrip,
)

BOUNDARY_ISSUE = "cutover_boundary"
ROLLBACK_DAYS = 30
LEGACY_VOID_REASONS = ("legacy_line_zeroed", "legacy_line_deleted")


class SwitchRefused(FinanceError):
    """Переключение или откат отклонены: reasons - перечень {code, message}."""

    def __init__(self, reasons: list[dict], what: str = "Переключение"):
        text = "; ".join(r["message"] for r in reasons)
        super().__init__("switch_refused", f"{what} отклонено: {text}", status_code=409)
        self.reasons = reasons


class _Rollback(Exception):  # noqa: N818 - служебный откат пробного запуска
    pass


def _reason(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _company(company_id: int) -> Company:
    company = Company.objects.filter(pk=company_id).first()
    if company is None:
        raise FinanceError("company_not_found", "Компания не найдена", status_code=404)
    return company


def _settings_row(company, *, lock: bool = False) -> CompanyFinancialSettings:
    get_settings(company)  # строка настроек есть у каждой компании
    qs = CompanyFinancialSettings.objects
    return (qs.select_for_update() if lock else qs).get(company_id=company.pk)


def _run_reconcile(company_id: int, *, dry_run: bool):
    """Сверка; в пробном запуске откатывается (ничего не пишется)."""
    if not dry_run:
        return reconcile.reconcile(company_id)
    box = {}
    try:
        with transaction.atomic():
            run = reconcile.reconcile(company_id)
            box["status"], box["unexplained"] = run.status, run.summary.get("unexplained", 0)
            box["findings"] = run.summary.get("findings", [])[:20]
            box["not_reflected"] = run.summary.get("not_reflected", [])
            raise _Rollback
    except _Rollback:
        pass
    return type("DryRun", (), {"pk": None, "status": box["status"], "summary": box})()


def _open_error_issues(cid: int) -> int:
    with tenant_context(cid):
        return FinanceMigrationIssue.objects.filter(status="open", severity="error").count()


# --- legacy -> shadow -----------------------------------------------------------------------


@transaction.atomic
def switch_to_shadow(
    company_id: int, *, approval_ref: str, user=None, dry_run: bool = False
) -> dict:
    company = _company(company_id)
    reasons = []
    if not (approval_ref or "").strip():
        reasons.append(_reason("approval_ref_missing", "Не указана ссылка на разрешение заказчика"))
    with tenant_context(company.pk):
        row = _settings_row(company, lock=True)
        if row.engine != "legacy":
            reasons.append(
                _reason(
                    "engine_not_legacy",
                    f"В shadow можно перейти только из legacy (сейчас {row.engine})",
                )
            )
        if reasons:
            raise SwitchRefused(reasons)
        result = {"company": company.pk, "from": "legacy", "to": "shadow", "dry_run": dry_run}
        if dry_run:
            return result
        row.engine = "shadow"
        row.save()
        audit.log(
            "update",
            row,
            user,
            {
                "engine": ["legacy", "shadow"],
                "approval_ref": approval_ref.strip(),
                "source": "switch_finance_engine",
            },
        )
        return result


# --- shadow -> new --------------------------------------------------------------------------


def check_switch_to_new(
    company, *, cutover, approval_ref, dry_run=False
) -> tuple[list[dict], object]:
    """(причины отказа, запуск сверки). Сверка выполняется всегда (в пробном - с откатом)."""
    reasons: list[dict] = []
    with tenant_context(company.pk):
        row = _settings_row(company)
        if row.engine != "shadow":
            reasons.append(
                _reason(
                    "engine_not_shadow",
                    f"На new можно перейти только из shadow (сейчас {row.engine})",
                )
            )
        if row.financial_writes_frozen:
            reasons.append(_reason("writes_frozen", "Финансовые изменения заморожены"))
    if cutover is None:
        reasons.append(_reason("cutover_missing", "Не задана дата cutover (--cutover)"))
    if not (approval_ref or "").strip():
        reasons.append(_reason("approval_ref_missing", "Не указана ссылка на разрешение заказчика"))
    reasons.extend(status_mapping.switch_blockers(company))
    run = _run_reconcile(company.pk, dry_run=dry_run)
    if run.status != "success":
        reasons.append(
            _reason(
                "reconcile_not_success",
                f"Сверка не успешна: статус {run.status}, необъяснённых расхождений {run.summary.get('unexplained', '?')}",
            )
        )
    if run.summary.get("not_reflected"):
        reasons.append(
            _reason(
                "not_reflected_amounts",
                f"Есть суммы, не отражённые в новой модели: {len(run.summary['not_reflected'])} "
                "(открытые проблемы или обоснованные исключения)",
            )
        )
    errors = _open_error_issues(company.pk)
    if errors:
        reasons.append(_reason("open_error_issues", f"Открытых проблем уровня error: {errors}"))
    return reasons, run


def _clear_recognition(income: Income) -> None:
    income.status = "planned"
    income.recognized_on = None
    income.recognition_basis = ""
    income.trip = None
    income.fx_base_currency = None
    income.fx_rate = None
    income.fx_rate_date = None
    income.fx_rate_source = ""
    income.base_amount = None


def apply_cutover_rule(company, cutover: date, *, user, approval_ref: str, write: bool) -> dict:
    """Правило 1.4.4 для доходов перевозки с датой не раньше cutover.

    Доходы, признанные ДО cutover, не меняются (историческая корректность, legacy_line_date).
    Остальные: все действующие рейсы завершены -> признание на дату завершения последнего рейса;
    иначе planned. Завершение раньше cutover при строке позже cutover -> Issue cutover_boundary,
    запись остаётся как была. Услуги не меняются. Закрытый период -> FinanceError (всё откатывается).
    """
    cid = company.pk
    settings = income_svc.get_settings_for(cid)
    counters = {
        "before_cutover": 0,
        "recognized": 0,
        "to_planned": 0,
        "unchanged": 0,
        "boundary": 0,
        "skipped_orders": 0,
    }
    ids = list(
        Income.objects.filter(kind="freight")
        .exclude(status="void")
        .order_by("order_id")
        .values_list("pk", "order_id")
    )
    for income_pk, order_id in ids:
        order = (Order.all_objects.select_for_update() if write else Order.all_objects).get(
            pk=order_id
        )
        income = (Income.objects.select_for_update() if write else Income.objects).get(pk=income_pk)
        if income.status == "recognized" and income.recognized_on < cutover:
            counters["before_cutover"] += 1
            continue
        if order.deleted_at is not None or (order.status and order.status.code == "cancelled"):
            counters["skipped_orders"] += 1
            continue
        done, trips = income_svc.completion_state(order, settings, lock=write)
        if done:
            completed = [(local_date(t.completed_at, cid), t.completed_at, t.pk, t) for t in trips]
            recognized_on = max(c[0] for c in completed)
            if (
                income.status == "recognized"
                and income.recognition_basis == "trip_completed"
                and income.recognized_on == recognized_on
            ):
                counters["unchanged"] += 1
                continue
            if recognized_on < cutover:
                counters["boundary"] += 1
                if write:
                    _boundary_issue(cid, income, recognized_on, cutover, approval_ref)
                continue
            counters["recognized"] += 1
            if not write:
                continue
            if income.status == "recognized":
                periods.assert_period_open(cid, income.recognized_on)
            periods.assert_period_open(cid, recognized_on)
            before = income_svc._state(income)
            last_trip = max(completed, key=lambda c: (c[1], c[2]))[3]
            snapshot = fx_snapshot(company, income.amount, income.currency, recognized_on, settings)
            income.status = "recognized"
            income.recognized_on = recognized_on
            income.recognition_basis = "trip_completed"
            income.trip = last_trip
            for key, value in snapshot.items():
                setattr(income, key, value)
            income.save()
            income_svc._set_trips(income, [c[3] for c in completed])
            audit.log(
                "update",
                income,
                user,
                {
                    "cutover_rule": [before, income_svc._state(income)],
                    "approval_ref": approval_ref.strip(),
                },
            )
        elif income.status == "recognized":
            counters["to_planned"] += 1
            if not write:
                continue
            periods.assert_period_open(cid, income.recognized_on)
            before = income_svc._state(income)
            IncomeTrip.objects.filter(income=income).delete()
            _clear_recognition(income)
            income.save()
            audit.log(
                "update",
                income,
                user,
                {
                    "cutover_rule": [before, income_svc._state(income)],
                    "approval_ref": approval_ref.strip(),
                },
            )
        else:
            counters["unchanged"] += 1
    return counters


def _boundary_issue(cid, income, completed_on, cutover, approval_ref) -> None:
    exists = FinanceMigrationIssue.objects.filter(
        issue_type=BOUNDARY_ISSUE, source_model="finance.income", source_id=income.pk, status="open"
    ).exists()
    if exists:
        return
    FinanceMigrationIssue.objects.create(
        company_id=cid,
        issue_type=BOUNDARY_ISSUE,
        severity="warning",
        source_model="finance.income",
        source_id=income.pk,
        message=(
            f"Заказ завершён {completed_on:%d.%m.%Y}, раньше cutover {cutover:%d.%m.%Y}, "
            f"а доход учтён позже ({income.recognized_on or 'planned'}): запись оставлена как была"
        ),
        details={
            "order": income.order_id,
            "completed_on": completed_on.isoformat(),
            "cutover": cutover.isoformat(),
            "recognized_on": income.recognized_on.isoformat() if income.recognized_on else None,
            "approval_ref": approval_ref.strip(),
        },
    )


def switch_to_new(
    company_id: int, *, cutover, approval_ref: str, user=None, dry_run: bool = False
) -> dict:
    company = _company(company_id)
    if cutover is not None and not isinstance(cutover, date):
        raise FinanceError("cutover_invalid", "Дата cutover некорректна")
    reasons, run = check_switch_to_new(
        company, cutover=cutover, approval_ref=approval_ref, dry_run=dry_run
    )
    if reasons:
        raise SwitchRefused(reasons)
    result = {
        "company": company.pk,
        "from": "shadow",
        "to": "new",
        "cutover": cutover.isoformat(),
        "reconcile_run": run.pk,
        "dry_run": dry_run,
    }
    try:
        with transaction.atomic(), tenant_context(company.pk):
            row = _settings_row(company, lock=True)
            if (
                row.engine != "shadow" or row.financial_writes_frozen
            ):  # повторная проверка под блокировкой
                raise SwitchRefused(
                    [_reason("state_changed", "Состояние компании изменилось: повторите")]
                )
            counters = apply_cutover_rule(
                company, cutover, user=user, approval_ref=approval_ref, write=not dry_run
            )
            result["changes"] = counters
            if dry_run:
                raise _Rollback
            row.engine = "new"
            row.cutover_date = cutover
            row.engine_switched_at = timezone.now()
            row.updated_by = user if getattr(user, "pk", None) else None
            row.save()
            audit.log(
                "update",
                row,
                user,
                {
                    "engine": ["shadow", "new"],
                    "cutover_date": cutover.isoformat(),
                    "approval_ref": approval_ref.strip(),
                    "reconcile_run": run.pk,
                    "changes": counters,
                    "source": "switch_finance_engine",
                },
            )
    except _Rollback:
        pass
    return result


# --- откат ----------------------------------------------------------------------------------


def native_records(cid: int) -> list[dict]:
    """Записи новой модели, которых нет в старой (создание нативно в engine=new и ручные правки)."""
    out: list[dict] = []
    with tenant_context(cid):
        native_income = Income.objects.filter(legacy_line__isnull=True).exclude(
            status="void", void_reason__in=LEGACY_VOID_REASONS
        )
        if n := native_income.count():
            out.append(_reason("native_income", f"Доходов без строки прежнего учёта: {n}"))
        if n := Income.objects.filter(recognition_basis="manual_adjustment").count():
            out.append(_reason("manual_adjustment", f"Доходов с ручной корректировкой: {n}"))
        native_expense = Expense.objects.filter(legacy_group_key="").exclude(
            status="void", void_reason__in=LEGACY_VOID_REASONS
        )
        if n := native_expense.count():
            out.append(_reason("native_expense", f"Расходов без ключа прежнего учёта: {n}"))
        if (
            n := Expense.objects.filter(status="void")
            .exclude(void_reason__in=LEGACY_VOID_REASONS)
            .count()
        ):
            out.append(
                _reason("void_expense", f"Аннулированных расходов не из-за удаления строки: {n}")
            )
        if n := ExpenseAllocation.objects.filter(
            legacy_line__isnull=True, expense__status="active"
        ).count():
            out.append(
                _reason("native_allocation", f"Долей расходов без строки прежнего учёта: {n}")
            )
        row = CompanyFinancialSettings.objects.filter(company_id=cid).first()
        if row and row.engine_switched_at:
            if n := ExpenseInvoiceAllocation.objects.filter(
                created_at__gt=row.engine_switched_at
            ).count():
                out.append(
                    _reason(
                        "native_invoice_links",
                        f"Связей со счетами, созданных после переключения: {n}",
                    )
                )
    return out


def check_rollback(company, to: str, *, approval_ref: str, dry_run: bool = False, now=None):
    reasons: list[dict] = []
    now = now or timezone.now()
    if to not in ("shadow", "legacy"):
        reasons.append(_reason("target_invalid", "Откат возможен только на shadow или legacy"))
    if not (approval_ref or "").strip():
        reasons.append(_reason("approval_ref_missing", "Не указана ссылка на разрешение заказчика"))
    with tenant_context(company.pk):
        row = _settings_row(company)
        if row.engine != "new":
            reasons.append(
                _reason("engine_not_new", f"Откат возможен только из new (сейчас {row.engine})")
            )
        elif row.engine_switched_at is None:
            reasons.append(_reason("switched_at_missing", "Не известна дата переключения"))
        elif now - row.engine_switched_at > timedelta(days=ROLLBACK_DAYS):
            reasons.append(
                _reason(
                    "rollback_window_expired", f"С переключения прошло больше {ROLLBACK_DAYS} дней"
                )
            )
    reasons.extend(native_records(company.pk))
    run = _run_reconcile(company.pk, dry_run=dry_run)
    if run.status != "success":
        reasons.append(
            _reason(
                "reconcile_not_success",
                f"Полная сверка не успешна: статус {run.status}, необъяснённых расхождений {run.summary.get('unexplained', '?')}",
            )
        )
    return reasons, run


def rollback_engine(
    company_id: int, to: str, *, approval_ref: str, user=None, dry_run=False, now=None
) -> dict:
    """Возвращает engine; ничего не удаляет. Отказ - SwitchRefused с перечнем причин."""
    company = _company(company_id)
    reasons, run = check_rollback(company, to, approval_ref=approval_ref, dry_run=dry_run, now=now)
    if reasons:
        raise SwitchRefused(reasons, "Откат")
    result = {
        "company": company.pk,
        "from": "new",
        "to": to,
        "reconcile_run": run.pk,
        "dry_run": dry_run,
    }
    if dry_run:
        return result
    with transaction.atomic(), tenant_context(company.pk):
        row = _settings_row(company, lock=True)
        if row.engine != "new":
            raise SwitchRefused(
                [_reason("state_changed", "Состояние компании изменилось")], "Откат"
            )
        row.engine = to
        row.updated_by = user if getattr(user, "pk", None) else None
        row.save()
        audit.log(
            "update",
            row,
            user,
            {
                "engine": ["new", to],
                "approval_ref": approval_ref.strip(),
                "reconcile_run": run.pk,
                "source": "rollback_finance_engine",
            },
        )
    return result


# --- безопасная остановка -------------------------------------------------------------------


@transaction.atomic
def set_frozen(company_id: int, on: bool, *, reason: str, user=None) -> CompanyFinancialSettings:
    reason = (reason or "").strip()
    if not reason:
        raise FinanceError("reason_required", "Укажите причину")
    company = _company(company_id)
    with tenant_context(company.pk):
        row = _settings_row(company, lock=True)
        if row.financial_writes_frozen == on:
            return row
        row.financial_writes_frozen = on
        row.updated_by = user if getattr(user, "pk", None) else None
        row.save()
        audit.log(
            "update",
            row,
            user,
            {"financial_writes_frozen": [not on, on], "reason": reason, "source": "freeze_finance"},
        )
        return row
