"""Долги, просрочка и курсовые разницы в БАЗОВОЙ валюте компании (подзадача 1.4.14, engine=new).

Исходные суммы, валюты и курсы счетов/оплат НЕ меняются: все показатели - отдельные вычисления.

Задолженность (дебиторская - исходящие счета status=issued, кредиторская - входящие) на дату отчёта
as_of (по умолчанию сегодня компании): остаток счёта (total_gross - оплаты не позже as_of) в
ИСХОДНОЙ валюте + эквивалент в базовой валюте по курсу на as_of (fx.resolve_rate: тот же код /
прямой / через KZT, последний курс не позже даты). Применённый курс возвращается
(rate, rate_date, source).
Просрочка: остаток счетов с due_date раньше as_of (при as_of = сегодня - как прежде).

Курсовые разницы РАЗДЕЛЬНО и без общего итога:
  реализованная   - по оплатам периода: amount * (rate_to_base платежа - rate_to_base счёта),
                    знак по направлению (out: плюс - прибыль; in: плюс курса - убыток);
  нереализованная - по ОТКРЫТОМУ остатку на as_of: остаток * (курс as_of - rate_to_base счёта),
                    тот же знак. Оплаченная часть уходит в реализованную - пересечения нет.
Курсовые разницы не входят в Income/Expense/прибыль/маржу (этот модуль их не касается).

Не смешивать базы. Причины, по которым запись выпадает из итогов (excluded, по исходной валюте):
  no_rate      - нет курса на дату отчёта: эквивалента в базе нет вообще;
  prior_base   - снимок счёта сделан в ДРУГОЙ базовой валюте: в итоги базы не входит, эквивалент на
                 дату отчёта показывается отдельно (equivalent_base) и в итоги не суммируется;
  no_base_rate - у счёта нет базового курса (выпущен до введения снимков): эквивалент на дату
                 отчёта входит в balance_base/overdue_base, но carrying_base и нереализованная
                 разница не считаются (курс не придумывается).
Счёт в валюте, равной базовой, всегда пригоден (курс 1, разница 0).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from apps.core.handbooks.models import HandbookValue
from apps.core.models import Company
from apps.core.tenancy import get_current_company_id, tenant_context
from apps.forwarding.models import Carrier, Client

from . import fx
from .errors import FinanceError
from .models import Invoice, Payment
from .money import ZERO, fx_difference, quantize_money

OK = "ok"
NO_RATE = "no_rate"
PRIOR_BASE = "prior_base"
NO_BASE_RATE = "no_base_rate"
REASONS = (NO_RATE, PRIOR_BASE, NO_BASE_RATE)
ONE = Decimal("1")


# --- общее ------------------------------------------------------------------------------------


@dataclass
class Context:
    company: Company
    base: HandbookValue
    as_of: date
    rates: dict = field(default_factory=dict)  # currency_id -> (rate, source, rate_date) | None


def make_context(as_of: date, company_id: int | None = None) -> Context:
    cid = company_id or get_current_company_id()
    company = Company.objects.get(pk=cid)
    settings = fx.get_settings(company)
    base = settings.base_currency
    if base is None:
        with tenant_context(cid):
            base = HandbookValue.objects.filter(handbook__code="currency", code="KZT").first()
    if base is None:
        raise FinanceError(
            "base_currency_missing", "Не задана базовая валюта компании", status_code=409
        )
    return Context(company=company, base=base, as_of=as_of)


def base_info(company_id: int | None = None) -> dict:
    """{'id', 'code'} базовой валюты компании (для оплат и журналов)."""
    base = make_context(date.min, company_id).base
    return {"id": base.pk, "code": base.code}


def rate_for(ctx: Context, currency: HandbookValue):
    """(курс, источник, дата курса) на дату отчёта или None (курса нет); кэш по валюте."""
    if currency.pk not in ctx.rates:
        try:
            ctx.rates[currency.pk] = fx.resolve_rate(ctx.company, currency, ctx.base, ctx.as_of)
        except FinanceError as exc:
            if getattr(exc.detail, "code", None) != "rate_missing":
                raise
            ctx.rates[currency.pk] = None
    return ctx.rates[currency.pk]


def sign(direction: str) -> int:
    return 1 if direction == "out" else -1


# --- записи задолженности (по одному открытому счёту) ----------------------------------------


@dataclass
class Entry:
    invoice_id: int
    party_id: int
    direction: str
    currency_id: int
    currency_code: str
    gross: Decimal
    paid: Decimal
    overdue: bool
    kzt_rate: Decimal | None
    inv_rate_base: Decimal | None = None  # курс счёта к текущей базе (None - нет/другая база)
    status: str = OK
    applied: tuple | None = None  # (rate, source, rate_date)
    current_base: Decimal | None = None
    carrying_base: Decimal | None = None
    unrealized: Decimal | None = None

    @property
    def open(self) -> Decimal:
        return self.gross - self.paid


def _classify(entry: Entry, inv_base_id, inv_rate, ctx: Context, currency: HandbookValue) -> None:
    """Заполняет status, применённый курс, эквивалент, балансовую стоимость и разницу."""
    open_ = entry.open
    entry.applied = rate_for(ctx, currency)
    if entry.applied is None:
        entry.status = NO_RATE
        return
    rate = entry.applied[0]
    entry.current_base = quantize_money(open_ * rate)
    if currency.pk == ctx.base.pk:  # курс 1 по определению: разницы нет
        entry.inv_rate_base = ONE
        entry.carrying_base = quantize_money(open_)
        entry.unrealized = ZERO
        return
    if inv_base_id is None or inv_rate is None:
        entry.status = NO_BASE_RATE
        return
    if inv_base_id != ctx.base.pk:
        entry.status = PRIOR_BASE
        return
    entry.inv_rate_base = inv_rate
    entry.carrying_base = quantize_money(open_ * inv_rate)
    entry.unrealized = sign(entry.direction) * quantize_money(open_ * (rate - inv_rate)) + ZERO


def load_entries(direction: str, ctx: Context) -> list[Entry]:
    """Выставленные счета направления на as_of с остатками. Число запросов постоянно."""
    party_field = "client_id" if direction == "out" else "carrier_id"
    as_of = ctx.as_of
    invoices = list(
        Invoice.objects.filter(direction=direction, status="issued")
        .filter(Q(issue_date__lte=as_of) | Q(issue_date__isnull=True))
        .order_by("id")
        .values(
            "id",
            party_field,
            "currency_id",
            "total_gross",
            "due_date",
            "rate_to_kzt",
            "base_currency_id",
            "rate_to_base",
        )
    )
    paid = {
        r["invoice_id"]: r["paid"]
        for r in Payment.objects.filter(
            invoice__direction=direction, invoice__status="issued", date__lte=as_of
        )
        .order_by()
        .values("invoice_id")
        .annotate(paid=Sum("amount"))
    }
    currencies = {
        c.pk: c for c in HandbookValue.objects.filter(pk__in={i["currency_id"] for i in invoices})
    }
    entries = []
    for inv in invoices:
        currency = currencies[inv["currency_id"]]
        entry = Entry(
            invoice_id=inv["id"],
            party_id=inv[party_field],
            direction=direction,
            currency_id=currency.pk,
            currency_code=currency.code,
            gross=inv["total_gross"],
            paid=paid.get(inv["id"], ZERO),
            overdue=inv["due_date"] is not None and inv["due_date"] < as_of,
            kzt_rate=inv["rate_to_kzt"],
        )
        if entry.open > 0:
            _classify(entry, inv["base_currency_id"], inv["rate_to_base"], ctx, currency)
        entries.append(entry)
    return entries


# --- агрегирование по контрагентам -------------------------------------------------------------


def _empty_excluded() -> dict:
    return {r: {"count": 0, "by_currency": {}} for r in REASONS}


def _add_excluded(excluded: dict, entry: Entry) -> None:
    part = excluded[entry.status]
    part["count"] += 1
    cell = part["by_currency"].setdefault(
        entry.currency_code, {"open": ZERO, "overdue": ZERO, "equivalent_base": ZERO}
    )
    cell["open"] += entry.open
    if entry.overdue:
        cell["overdue"] += entry.open
    if entry.status == PRIOR_BASE and entry.current_base is not None:
        cell["equivalent_base"] += entry.current_base  # справочно, в итоги не суммируется


def finalize_excluded(excluded: dict) -> dict:
    count = sum(excluded[r]["count"] for r in REASONS)
    return {"is_partial": count > 0, "count": count, **excluded}


def _totals() -> dict:
    return {
        "balance_base": ZERO,
        "overdue_base": ZERO,
        "carrying_base": ZERO,
        "revalued_base": ZERO,
        "unrealized_diff": ZERO,
    }


def _accumulate(totals: dict, entry: Entry) -> None:
    """Вклад записи в итоги базы (только пригодные; см. описание модуля)."""
    if entry.status in (OK, NO_BASE_RATE):
        totals["balance_base"] += entry.current_base
        if entry.overdue:
            totals["overdue_base"] += entry.current_base
    if entry.status == OK:
        totals["carrying_base"] += entry.carrying_base
        totals["revalued_base"] += entry.current_base
        totals["unrealized_diff"] += entry.unrealized


def _rate_info(applied):
    rate, source, rate_date = applied
    return {"rate": rate, "rate_date": rate_date, "source": source}


def build_rows(entries: list[Entry], direction: str) -> tuple[list[dict], dict]:
    """(строки по контрагентам, итоги направления). Ключи *_kzt - прежние (KZT по курсу счёта)."""
    model = Client if direction == "out" else Carrier
    rows: dict[int, dict] = {}
    groups = defaultdict(lambda: {"gross": ZERO, "paid": ZERO})  # как прежний debts._groups
    for e in entries:
        row = rows.setdefault(e.party_id, _new_row(e.party_id))
        cur = row["by_currency"].setdefault(
            e.currency_code,
            {
                "issued": ZERO,
                "paid": ZERO,
                "balance": ZERO,
                "overdue": ZERO,
                "balance_base": ZERO,
                "overdue_base": ZERO,
                "carrying_base": ZERO,
                "revalued_base": ZERO,
                "unrealized_diff": ZERO,
                "applied_rate": None,
                "excluded": _empty_excluded(),
            },
        )
        cur["issued"] += e.gross
        cur["paid"] += e.paid
        cur["balance"] += e.open
        if e.kzt_rate is not None:
            groups[(e.party_id, e.currency_code, e.kzt_rate, e.overdue)]["gross"] += e.gross
            groups[(e.party_id, e.currency_code, e.kzt_rate, e.overdue)]["paid"] += e.paid
        if e.open <= 0:
            continue
        if e.overdue:
            cur["overdue"] += e.open
        if e.applied is not None:
            cur["applied_rate"] = _rate_info(e.applied)
        if e.status != OK:
            _add_excluded(cur["excluded"], e)
            _add_excluded(row["excluded"], e)
        _accumulate(cur, e)
        _accumulate(row, e)
    for (party_id, _code, rate, is_od), v in groups.items():
        row = rows[party_id]
        balance = v["gross"] - v["paid"]
        row["issued_kzt"] += quantize_money(v["gross"] * rate)
        row["paid_kzt"] += quantize_money(v["paid"] * rate)
        row["balance_kzt"] += quantize_money(balance * rate)
        if is_od:
            row["overdue_kzt"] += quantize_money(balance * rate)
    parties = {p.pk: p for p in model.objects.filter(pk__in=rows)}
    totals = _totals()
    excluded_all = _empty_excluded()
    for pid, row in rows.items():
        row["name"] = parties[pid].name if pid in parties else ""
        row["balance"] = {c: v["balance"] for c, v in row["by_currency"].items() if v["balance"]}
        row["overdue"] = {c: v["overdue"] for c, v in row["by_currency"].items() if v["overdue"]}
        row["applied_rate"] = {
            c: v["applied_rate"] for c, v in row["by_currency"].items() if v["applied_rate"]
        }
        row["excluded"] = finalize_excluded(row["excluded"])
        row["is_partial"] = row["excluded"]["is_partial"]
        for c in row["by_currency"].values():
            c["excluded"] = finalize_excluded(c["excluded"])
        for key in totals:
            totals[key] += row[key]
        for reason in REASONS:
            part = row["excluded"][reason]
            dst = excluded_all[reason]
            dst["count"] += part["count"]
            for code, cell in part["by_currency"].items():
                into = dst["by_currency"].setdefault(
                    code, {"open": ZERO, "overdue": ZERO, "equivalent_base": ZERO}
                )
                for k, v in cell.items():
                    into[k] += v
        if model is Client:
            limit = parties[pid].credit_limit if pid in parties else ZERO
            row["credit_limit"] = limit
            row["limit_usage_pct"] = (
                quantize_money(row["balance_kzt"] / limit * 100) if limit else None
            )
    ordered = sorted(rows.values(), key=lambda r: (-r["balance_kzt"], r["name"]))
    return ordered, {**totals, "excluded": finalize_excluded(excluded_all)}


def _new_row(party_id: int) -> dict:
    return {
        "id": party_id,
        "issued_kzt": ZERO,
        "paid_kzt": ZERO,
        "balance_kzt": ZERO,
        "overdue_kzt": ZERO,
        "by_currency": {},
        **_totals(),
        "excluded": _empty_excluded(),
    }


def debts_report(direction: str, as_of: date) -> dict:
    """Живой отчёт по задолженности направления на as_of (контекст компании - текущий)."""
    ctx = make_context(as_of)
    rows, totals = build_rows(load_entries(direction, ctx), direction)
    return {
        "source": "live",
        "snapshot": None,
        "base_currency": ctx.base.code,
        "as_of": as_of,
        "is_partial": totals["excluded"]["is_partial"],
        "excluded": totals["excluded"],
        "totals": {k: v for k, v in totals.items() if k != "excluded"},
        "results": rows,
    }


# --- реализованная курсовая разница по оплатам -------------------------------------------------


def payment_realized(row: dict, base_id: int):
    """(разница в базе | None, статус) по значениям оплаты и её счёта (см. realized_rows)."""
    if row["invoice__currency_id"] == base_id:
        return ZERO, OK
    if (
        row["rate_to_base"] is None
        or row["invoice__rate_to_base"] is None
        or row["base_currency_id"] is None
        or row["invoice__base_currency_id"] is None
    ):
        return None, NO_BASE_RATE
    if row["base_currency_id"] != base_id or row["invoice__base_currency_id"] != base_id:
        return None, PRIOR_BASE
    diff = fx_difference(
        row["amount"], row["rate_to_base"], row["invoice__rate_to_base"], row["invoice__direction"]
    )
    return diff + ZERO, OK  # + ZERO: «-0.00» -> «0.00»


PAYMENT_VALUES = (
    "id",
    "date",
    "amount",
    "invoice_id",
    "invoice__number",
    "invoice__direction",
    "invoice__currency_id",
    "invoice__currency__code",
    "invoice__rate_to_base",
    "invoice__base_currency_id",
    "base_currency_id",
    "rate_to_base",
)


def realized_rows(qs, base_id: int) -> list[dict]:
    """Оплаты queryset со значением реализованной разницы (fx_realized_base, fx_status)."""
    out = []
    for row in qs.order_by("-date", "-id").values(*PAYMENT_VALUES):
        diff, status = payment_realized(row, base_id)
        out.append({**row, "fx_realized_base": diff, "fx_status": status})
    return out


def realized_summary(rows: list[dict]) -> dict:
    """Итог реализованной разницы по пригодным оплатам и исключённое (в исходной валюте)."""
    total = ZERO
    by_direction = {"out": ZERO, "in": ZERO}
    excluded = {r: {"count": 0, "by_currency": {}} for r in (PRIOR_BASE, NO_BASE_RATE)}
    for r in rows:
        if r["fx_status"] == OK:
            total += r["fx_realized_base"]
            by_direction[r["invoice__direction"]] += r["fx_realized_base"]
            continue
        part = excluded[r["fx_status"]]
        part["count"] += 1
        code = r["invoice__currency__code"]
        part["by_currency"][code] = part["by_currency"].get(code, ZERO) + r["amount"]
    count = sum(p["count"] for p in excluded.values())
    return {
        "fx_realized_base": total,
        "by_direction": by_direction,
        "is_partial": count > 0,
        "excluded": {"count": count, **excluded},
    }


def realized_for_period(date_from: date | None, date_to: date | None, base_id: int) -> dict:
    qs = Payment.objects.filter(invoice__status="issued")
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    return realized_summary(realized_rows(qs, base_id))


# --- финансовая сводка ------------------------------------------------------------------------


def summary_extras(today: date, first: date, last: date) -> dict:
    """Новые поля сводки (engine=new): долги и просрочка в базе, реализованная и нереализованная
    разницы раздельно. Реализованная - за месяц [first, last], нереализованная - на today."""
    ctx = make_context(today)
    clients, c_tot = build_rows(load_entries("out", ctx), "out")
    carriers, p_tot = build_rows(load_entries("in", ctx), "in")
    realized = realized_for_period(first, last, ctx.base.pk)
    excl = _empty_excluded()
    for tot in (c_tot, p_tot):
        for reason in REASONS:
            excl[reason]["count"] += tot["excluded"][reason]["count"]
            for code, cell in tot["excluded"][reason]["by_currency"].items():
                into = excl[reason]["by_currency"].setdefault(
                    code, {"open": ZERO, "overdue": ZERO, "equivalent_base": ZERO}
                )
                for k, v in cell.items():
                    into[k] += v
    return {
        "base_currency": ctx.base.code,
        "client_debt_base": c_tot["balance_base"],
        "overdue_base": c_tot["overdue_base"],
        "payable_base": p_tot["balance_base"],
        "payable_overdue_base": p_tot["overdue_base"],
        "fx_realized_base": realized["fx_realized_base"],
        "fx_realized_partial": realized["is_partial"],
        "fx_realized_excluded": realized["excluded"],
        "fx_unrealized_base": c_tot["unrealized_diff"] + p_tot["unrealized_diff"],
        "fx_unrealized_clients_base": c_tot["unrealized_diff"],
        "fx_unrealized_payables_base": p_tot["unrealized_diff"],
        "debts_partial": any(excl[r]["count"] for r in REASONS),
        "debts_excluded": finalize_excluded(excl),
    }
