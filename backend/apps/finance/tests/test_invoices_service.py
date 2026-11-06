import threading
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine
from django.db import connection

from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.finance import invoices as svc
from apps.finance.errors import FinanceError
from apps.finance.models import Invoice, Payment
from apps.finance.tests.helpers import (
    add_line,
    cur,
    first_user,
    make_carrier,
    make_client,
    make_order,
    set_rate,
    vat,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=dt_tz.utc)


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


def code(exc):
    return exc.value.detail.code


def draft(company, order, lines, *, client=None, currency="KZT", percent="16", **extra):
    """Черновик счёта клиенту по строкам заказа: lines - [(строка, сумма)]."""
    user = first_user(company)
    with tenant_context(company.id):
        return svc.create_draft(
            direction="out",
            party=client or order.client,
            order=order,
            trip=None,
            currency=cur(company, currency),
            vat_rate=vat(company, percent),
            items=[
                {"title": f"п{i}", "amount_net": amt, "line": ln}
                for i, (ln, amt) in enumerate(lines)
            ],
            user=user,
            **extra,
        )


def issue(company, invoice, **kw):
    with tenant_context(company.id):
        return svc.issue(invoice, user=first_user(company), **kw)


@pytest.fixture
def order(company):
    return make_order(company)


def test_issue_assigns_number_and_snapshot(company, order):
    line = add_line(company, order, income=1000)
    inv = draft(company, order, [(line, D("1000"))])
    out = issue(company, inv)
    assert out.number == "СЧ-2026-00001"
    assert out.status == "issued" and out.issue_date == date(2026, 10, 15)
    assert out.rate_to_kzt == D("1")
    assert (out.total_net, out.total_vat, out.total_gross) == (
        D("1000.00"),
        D("160.00"),
        D("1160.00"),
    )


def test_issue_twice_forbidden(company, order):
    line = add_line(company, order, income=100)
    inv = draft(company, order, [(line, D("100"))])
    issue(company, inv)
    with pytest.raises(FinanceError) as exc:
        issue(company, inv)
    assert code(exc) == "invoice_not_editable"


def test_issue_empty_invoice_rejected(company, order):
    inv = draft(company, order, [])
    with pytest.raises(FinanceError) as exc:
        issue(company, inv)
    assert code(exc) == "invoice_empty"


def test_currency_mismatch(company):
    set_rate(company, "USD", 450)
    order = make_order(company, currency="KZT")
    line = add_line(company, order, income=100)
    with pytest.raises(FinanceError) as exc:
        draft(company, order, [(line, D("100"))], currency="USD")
    assert code(exc) == "currency_mismatch"


def test_party_mismatch_other_clients_order(company, order):
    other = make_client(company, "ТОО Другой")
    line = add_line(company, order, income=100)
    with pytest.raises(FinanceError) as exc:
        draft(company, order, [(line, D("100"))], client=other)
    assert code(exc) == "party_mismatch"


def test_line_of_other_order_rejected(company, order):
    other_order = make_order(company, client=order.client)
    foreign = add_line(company, other_order, income=100)
    with pytest.raises(FinanceError) as exc:
        draft(company, order, [(foreign, D("100"))])
    assert code(exc) == "party_mismatch"


def test_line_in_two_active_invoices_rejected_and_cancel_frees(company, order):
    line = add_line(company, order, income=1000)
    first = draft(company, order, [(line, D("400"))])
    with pytest.raises(FinanceError) as exc:
        draft(company, order, [(line, D("100"))])
    assert code(exc) == "item_already_invoiced"
    issue(company, first)
    with tenant_context(company.id):
        svc.cancel(first, user=first_user(company))
    draft(company, order, [(line, D("100"))])  # после отмены строка свободна


def test_deleted_or_cancelled_order_line_rejected(company):
    for how in ("deleted", "cancelled"):
        order = make_order(company)
        line = add_line(company, order, income=100)
        with tenant_context(company.id):
            if how == "deleted":
                order.delete()
            else:
                from apps.core.handbooks.models import HandbookValue

                order.status = HandbookValue.objects.get(
                    handbook__code="order_status", code="cancelled"
                )
                order.save()
        with pytest.raises(FinanceError) as exc:
            draft(company, order, [(line, D("100"))])
        assert code(exc) == "line_unavailable"


def test_invoice_cannot_exceed_order_income(company, order):
    l1 = add_line(company, order, income=1000)
    l2 = add_line(company, order, income=500)
    first = draft(company, order, [(l1, D("1000"))])
    issue(company, first)
    second = draft(company, order, [(l2, D("600"))])  # 1000 + 600 > 1500
    with pytest.raises(FinanceError) as exc:
        issue(company, second)
    assert code(exc) == "invoice_exceeds_order_income"


def test_due_date_default_from_order_delay(company):
    order = make_order(company, payment_delay_days=10)
    line = add_line(company, order, income=100)
    out = issue(company, draft(company, order, [(line, D("100"))]))
    assert out.due_date == date(2026, 10, 25)
    explicit = draft(
        company, order, [(add_line(company, order, income=5), D("5"))], due_date=date(2026, 12, 1)
    )
    assert issue(company, explicit).due_date == date(2026, 12, 1)


def test_credit_limit_blocks_and_override(company):
    client = make_client(company, "С лимитом", credit_limit=1000)
    order = make_order(company, client=client)
    l1 = add_line(company, order, income=700)
    l2 = add_line(company, order, income=400)
    issue(company, draft(company, order, [(l1, D("700"))], percent="0"))  # долг 700 <= 1000
    second = draft(company, order, [(l2, D("400"))], percent="0")  # 700 + 400 > 1000
    with pytest.raises(FinanceError) as exc:
        issue(company, second)
    assert code(exc) == "credit_limit_exceeded"
    with pytest.raises(FinanceError) as exc:  # обход без причины не допускается
        issue(company, second, can_override=True, override_reason="")
    assert code(exc) == "credit_limit_exceeded"
    with pytest.raises(FinanceError):  # причина без права
        issue(company, second, can_override=False, override_reason="нужно")
    out = issue(company, second, can_override=True, override_reason="согласовано с директором")
    assert out.status == "issued"
    with tenant_context(company.id):
        assert AuditLog.objects.filter(
            changes__credit_limit_override="согласовано с директором"
        ).exists()


def test_zero_limit_means_no_limit(company, order):
    line = add_line(company, order, income=10**9)
    assert issue(company, draft(company, order, [(line, D("10000000"))])).status == "issued"


def test_missing_rate_blocks_issue(company):
    order = make_order(company, currency="USD")
    line = add_line(company, order, income=100)
    inv = draft(company, order, [(line, D("100"))], currency="USD")
    with pytest.raises(FinanceError) as exc:
        issue(company, inv)
    assert code(exc) == "rate_missing"
    set_rate(company, "USD", 450, day=date(2026, 10, 1))
    out = issue(company, inv)
    assert out.rate_to_kzt == D("450")


def test_cancel_with_payment_rejected(company, order):
    line = add_line(company, order, income=100)
    out = issue(company, draft(company, order, [(line, D("100"))]))
    with tenant_context(company.id):
        Payment.objects.create(
            company=company,
            invoice=out,
            date=date(2026, 10, 15),
            amount=D("10"),
            rate_to_kzt=D("1"),
            method="bank",
        )
        with pytest.raises(FinanceError) as exc:
            svc.cancel(out, user=first_user(company))
    assert code(exc) == "invoice_has_payments"


def test_display_status_boundary(company, order):
    line = add_line(company, order, income=100)
    out = issue(company, draft(company, order, [(line, D("100"))], due_date=date(2026, 10, 15)))
    assert svc.display_status(out, date(2026, 10, 15), paid=D("0")) == "issued"
    assert svc.display_status(out, date(2026, 10, 16), paid=D("0")) == "overdue"
    assert svc.display_status(out, date(2026, 10, 16), paid=D("50")) == "overdue"
    assert svc.display_status(out, date(2026, 10, 16), paid=out.total_gross) == "paid"
    assert svc.display_status(out, date(2026, 10, 10), paid=D("50")) == "partial"


def test_display_status_uses_company_timezone(company, order):
    line = add_line(company, order, income=100)
    out = issue(company, draft(company, order, [(line, D("100"))], due_date=date(2026, 10, 15)))
    # 19:30 UTC 15 октября = 00:30 16 октября в Asia/Almaty -> просрочен
    with time_machine.travel(datetime(2026, 10, 15, 19, 30, tzinfo=dt_tz.utc), tick=False):
        with tenant_context(company.id):
            assert svc.display_status(out, None) == "overdue"


def test_in_invoice_for_trip_and_numbering(company):
    from apps.forwarding.tests.test_trips import make_cargos, svc_create

    order, ids = make_cargos(company, 1)
    carrier = make_carrier(company)
    trip = svc_create(company, ids, carrier=carrier)
    exp = add_line(company, order, expense=800, title="Перевозка")
    user = first_user(company)
    with tenant_context(company.id):
        inv = svc.create_draft(
            direction="in",
            party=carrier,
            order=None,
            trip=trip,
            currency=cur(company),
            vat_rate=vat(company, "none"),
            external_number="А-77",
            items=[{"title": "Перевозка", "amount_net": D("800"), "line": exp}],
            user=user,
        )
        out = svc.issue(inv, user=user)
    assert out.number == "ПС-2026-00001" and out.external_number == "А-77"
    assert out.total_gross == D("800.00")


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_numbers_unique_under_concurrency(company):
    order = make_order(company)
    invs = []
    for _ in range(2):
        line = add_line(company, order, income=10)
        invs.append(draft(company, order, [(line, D("10"))], percent="0"))
    numbers, errors = [], []

    def run(inv):
        try:
            with tenant_context(company.id):
                numbers.append(svc.issue(inv, user=first_user(company)).number)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in invs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    assert len(set(numbers)) == 2


def test_update_issued_allows_only_light_fields(company, order):
    line = add_line(company, order, income=100)
    out = issue(company, draft(company, order, [(line, D("100"))]))
    with tenant_context(company.id):
        svc.update_issued(out, due_date=date(2027, 1, 1), comment="c", external_number="X1")
        out.refresh_from_db()
        assert out.due_date == date(2027, 1, 1) and out.comment == "c"
        with pytest.raises(FinanceError) as exc:
            svc.update_draft(out, comment="no")
    assert code(exc) == "invoice_not_editable"


def test_delete_draft_only(company, order):
    line = add_line(company, order, income=100)
    inv = draft(company, order, [(line, D("100"))])
    with tenant_context(company.id):
        svc.delete_draft(inv)
        assert not Invoice.objects.filter(pk=inv.pk).exists()
    inv2 = issue(company, draft(company, order, [(line, D("100"))]))
    with tenant_context(company.id):
        with pytest.raises(FinanceError) as exc:
            svc.delete_draft(inv2)
    assert code(exc) == "invoice_not_editable"


def test_annotate_paid_no_n_plus_one(company, order, django_assert_max_num_queries):
    lines = [add_line(company, order, income=10) for _ in range(5)]
    for ln in lines:
        issue(company, draft(company, order, [(ln, D("10"))], percent="0"))
    with tenant_context(company.id):
        with django_assert_max_num_queries(2):
            rows = list(svc.annotate_paid(Invoice.objects.all()))
            assert all(r.paid == 0 for r in rows)
