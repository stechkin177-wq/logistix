"""Снимки курсовой переоценки задолженности (FxRevaluation, 1.4.14).

Снимок создаётся при ЗАКРЫТИИ периода (periods.close_period при engine=new; курс на последний день
месяца; нехватка курса закрытие НЕ блокирует - строки получают статус no_rate) и по требованию
(POST /api/finance/fx-revaluations/). Снимки неизменны; отчёт по закрытому периоду читает
сохранённый снимок и не пересчитывается при последующем изменении курсов.
"""

from datetime import date

from django.db import transaction

from apps.core.audit import services as audit
from apps.core.tenancy import tenant_context

from . import debts_base as db
from .models import FxRevaluation, FxRevaluationLine
from .money import ZERO


def _s(value):
    return None if value is None else format(value, "f")


def _summary_part(totals: dict) -> dict:
    out = {k: _s(v) for k, v in totals.items() if k != "excluded"}
    ex = totals["excluded"]
    out["excluded"] = {
        "is_partial": ex["is_partial"],
        "count": ex["count"],
        **{
            r: {
                "count": ex[r]["count"],
                "by_currency": {
                    c: {k: _s(v) for k, v in cell.items()}
                    for c, cell in sorted(ex[r]["by_currency"].items())
                },
            }
            for r in db.REASONS
        },
    }
    return out


@transaction.atomic
def create_revaluation(company_id: int, as_of: date, kind: str, user, period=None) -> FxRevaluation:
    """Считает переоценку обоих направлений на as_of и сохраняет неизменяемый снимок."""
    with tenant_context(company_id):
        ctx = db.make_context(as_of, company_id)
        by_direction = {}
        lines = []
        for direction in ("out", "in"):
            entries = db.load_entries(direction, ctx)
            _rows, totals = db.build_rows(entries, direction)
            by_direction["clients" if direction == "out" else "carriers"] = _summary_part(totals)
            for e in entries:
                if e.open <= 0:
                    continue
                rate, source, rate_date = e.applied or (None, "", None)
                lines.append(
                    FxRevaluationLine(
                        company_id=company_id,
                        invoice_id=e.invoice_id,
                        direction=direction,
                        currency_id=e.currency_id,
                        open_balance=e.open,
                        invoice_rate_base=e.inv_rate_base,
                        carrying_base=e.carrying_base,
                        applied_rate=rate,
                        applied_rate_date=rate_date,
                        applied_rate_source=source,
                        current_base=e.current_base,
                        unrealized_diff=e.unrealized,
                        flags={"status": e.status, "overdue": e.overdue, "party_id": e.party_id},
                    )
                )
        clients, carriers = by_direction["clients"], by_direction["carriers"]
        summary = {
            "base_currency": ctx.base.code,
            "as_of": as_of.isoformat(),
            **by_direction,
            # отдельно по направлениям; общей «итоговой разницы» нет
            "unrealized_clients_base": clients["unrealized_diff"],
            "unrealized_payables_base": carriers["unrealized_diff"],
            "is_partial": clients["excluded"]["is_partial"] or carriers["excluded"]["is_partial"],
            "lines": len(lines),
        }
        reval = FxRevaluation.objects.create(
            company_id=company_id,
            as_of=as_of,
            kind=kind,
            base_currency=ctx.base,
            period=period,
            created_by=user if getattr(user, "pk", None) else None,
            summary=summary,
        )
        for line in lines:
            line.revaluation = reval
        FxRevaluationLine.objects.bulk_create(lines)
        audit.log(
            "create",
            reval,
            user,
            {"as_of": as_of.isoformat(), "kind": kind, "lines": len(lines)},
        )
        return reval


def snapshot_for_period(year: int, month: int) -> FxRevaluation | None:
    """Последний снимок закрытия периода (при повторном закрытии - самый свежий)."""
    return (
        FxRevaluation.objects.filter(kind="period_close", period__year=year, period__month=month)
        .select_related("base_currency")
        .order_by("-id")
        .first()
    )


def snapshot_entries(reval: FxRevaluation, direction: str) -> list[db.Entry]:
    """Записи задолженности из СОХРАНЁННОГО снимка (без пересчёта и без запросов курсов)."""
    out = []
    for line in reval.lines.filter(direction=direction).select_related("currency"):
        flags = line.flags or {}
        entry = db.Entry(
            invoice_id=line.invoice_id,
            party_id=flags.get("party_id"),
            direction=direction,
            currency_id=line.currency_id,
            currency_code=line.currency.code,
            gross=line.open_balance,
            paid=ZERO,
            overdue=bool(flags.get("overdue")),
            kzt_rate=None,
            inv_rate_base=line.invoice_rate_base,
            status=flags.get("status", db.OK),
            applied=(
                None
                if line.applied_rate is None
                else (line.applied_rate, line.applied_rate_source, line.applied_rate_date)
            ),
            current_base=line.current_base,
            carrying_base=line.carrying_base,
            unrealized=line.unrealized_diff,
        )
        out.append(entry)
    return out


def snapshot_report(reval: FxRevaluation, direction: str) -> dict:
    """Отчёт по задолженности направления, прочитанный из снимка."""
    rows, totals = db.build_rows(snapshot_entries(reval, direction), direction)
    for row in rows:  # в снимке нет начисленного/оплаченного в тенге: прежние поля не выдумываем
        for key in ("issued_kzt", "paid_kzt", "balance_kzt", "overdue_kzt"):
            row[key] = None
        if "limit_usage_pct" in row:
            row["limit_usage_pct"] = None
    rows.sort(key=lambda r: (-r["balance_base"], r["name"]))
    return {
        "source": "snapshot",
        "snapshot": {
            "id": reval.pk,
            "kind": reval.kind,
            "created_at": reval.created_at,
            "as_of": reval.as_of,
        },
        "base_currency": reval.base_currency.code,
        "as_of": reval.as_of,
        "is_partial": totals["excluded"]["is_partial"],
        "excluded": totals["excluded"],
        "totals": {k: v for k, v in totals.items() if k != "excluded"},
        "results": rows,
    }
