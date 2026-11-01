import threading
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

import pytest
import time_machine
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core.api.auth import issue_tokens
from apps.core.models import Membership, Role, User
from apps.core.numbering.models import NumberingRule
from apps.core.numbering.services import DEFAULTS, KINDS, next_number, seed_numbering
from apps.core.tenancy import NoTenantContext, tenant_context

pytestmark = pytest.mark.django_db

JUNE_2026 = datetime(2026, 6, 1, 12, 0, tzinfo=dt_tz.utc)
ALL_KINDS = [
    "order",
    "trip",
    "consolidated_trip",
    "invoice_out",
    "invoice_in",
    "contract",
    "act",
    "carrier_order",
    "cmr",
    "letter",
]


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(JUNE_2026, tick=False):
        yield


def rule(company, kind):
    with tenant_context(company.id):
        return NumberingRule.objects.get(kind=kind)


def num(company, kind, **ctx):
    with tenant_context(company.id):
        return next_number(kind, **ctx)


# --- сидинг ---


def test_kinds_and_defaults(company):
    assert sorted(KINDS) == sorted(ALL_KINDS)
    expected = {
        "order": ("ORD-{year}-{index}", 5),
        "trip": ("{order}-{n}", 5),
        "consolidated_trip": ("C{index}", 0),
        "invoice_out": ("СЧ-{year}-{index}", 5),
        "invoice_in": ("ПС-{year}-{index}", 5),
        "contract": ("Д-{year}-{index}", 5),
        "act": ("АКТ-{year}-{index}", 5),
        "carrier_order": ("ЗП-{year}-{index}", 5),
        "cmr": ("CMR-{year}-{index}", 5),
        "letter": ("ИСХ-{year}-{index}", 5),
    }
    assert {k: (v["template"], v["digits"]) for k, v in DEFAULTS.items()} == expected
    for kind, (template, digits) in expected.items():
        r = rule(company, kind)
        assert (r.template, r.digits, r.next_value) == (template, digits, 1)


def test_seed_is_idempotent_and_keeps_edits(company):
    with tenant_context(company.id):
        NumberingRule.objects.filter(kind="order").update(template="X-{index}", next_value=50)
    seed_numbering(company)
    seed_numbering(company)
    with tenant_context(company.id):
        assert NumberingRule.objects.count() == 10
    r = rule(company, "order")
    assert (r.template, r.next_value) == ("X-{index}", 50)


def test_unique_company_kind(company):
    with pytest.raises(IntegrityError), transaction.atomic():
        NumberingRule.all_objects.create(company=company, kind="order", template="{index}")


# --- рендер ---


def test_orders_sequential(company):
    assert num(company, "order") == "ORD-2026-00001"
    assert num(company, "order") == "ORD-2026-00002"
    assert rule(company, "order").next_value == 3


def test_trip_uses_context_and_no_counter(company):
    assert num(company, "trip", order="ORD-2026-00001", n=2) == "ORD-2026-00001-2"
    assert num(company, "trip", order="ORD-2026-00001", n=3) == "ORD-2026-00001-3"
    assert rule(company, "trip").next_value == 1


def test_trip_missing_context_names_key(company):
    with pytest.raises(ValueError, match="n"):
        num(company, "trip", order="ORD-1")
    with pytest.raises(ValueError, match="order"):
        num(company, "trip", n=1)
    assert rule(company, "trip").next_value == 1


def test_consolidated_trip_no_padding(company):
    assert num(company, "consolidated_trip") == "C1"
    assert num(company, "consolidated_trip") == "C2"


def test_invoices(company):
    assert num(company, "invoice_out") == "СЧ-2026-00001"
    assert num(company, "invoice_in") == "ПС-2026-00001"


def test_manual_next_value(company):
    with tenant_context(company.id):
        NumberingRule.objects.filter(kind="order").update(next_value=100)
    assert num(company, "order") == "ORD-2026-00100"
    assert num(company, "order") == "ORD-2026-00101"


def test_index_wider_than_digits_not_truncated(company):
    with tenant_context(company.id):
        NumberingRule.objects.filter(kind="order").update(next_value=123456)
    assert num(company, "order") == "ORD-2026-123456"


def test_unknown_kind(company):
    with pytest.raises(ValueError, match="bogus"):
        num(company, "bogus")


def test_fail_closed_without_tenant(company):
    with pytest.raises(NoTenantContext):
        next_number("order")


def test_works_inside_outer_transaction_and_rolls_back_together(company):
    try:
        with transaction.atomic():
            assert num(company, "order") == "ORD-2026-00001"
            raise RuntimeError
    except RuntimeError:
        pass
    # откат внешней транзакции откатывает и счётчик: пропусков нет
    assert num(company, "order") == "ORD-2026-00001"


def test_counters_isolated_between_companies(make_company):
    a, _, _ = make_company("A")
    b, _, _ = make_company("B")
    assert num(a, "order") == "ORD-2026-00001"
    assert num(a, "order") == "ORD-2026-00002"
    assert num(b, "order") == "ORD-2026-00001"


def test_year_uses_company_timezone_and_counter_is_continuous(company):
    """Год - в часовом поясе компании (Asia/Almaty, UTC+5); счётчик НЕ сбрасывается."""
    with time_machine.travel(datetime(2026, 12, 31, 18, 30, tzinfo=dt_tz.utc), tick=False):
        assert num(company, "order") == "ORD-2026-00001"  # 23:30 по Алматы
    with time_machine.travel(datetime(2026, 12, 31, 19, 30, tzinfo=dt_tz.utc), tick=False):
        assert num(company, "order") == "ORD-2027-00002"  # 00:30 1 января по Алматы


def test_year_differs_by_company_timezone(make_company):
    a, _, _ = make_company("A")
    b, _, _ = make_company("B")
    type(b).objects.filter(pk=b.pk).update(timezone="UTC")
    with time_machine.travel(datetime(2026, 12, 31, 19, 30, tzinfo=dt_tz.utc), tick=False):
        assert num(a, "order") == "ORD-2027-00001"
        assert num(b, "order") == "ORD-2026-00001"


# --- параллелизм ---


def _run_threads(company, total, workers, kind="order"):
    results, errors = [], []
    lock = threading.Lock()
    counter = iter(range(total))

    def worker():
        try:
            while True:
                with lock:
                    try:
                        next(counter)
                    except StopIteration:
                        return
                with tenant_context(company.id):
                    value = next_number(kind)
                with lock:
                    results.append(value)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    return results


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_threads_get_distinct_numbers(make_company):
    company, _, _ = make_company("Conc")
    results = _run_threads(company, 2, 2)
    assert len(set(results)) == 2


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_ten_calls_four_threads_gap_free(make_company):
    company, _, _ = make_company("Conc10")
    results = _run_threads(company, 10, 4)
    assert sorted(results) == [f"ORD-2026-{i:05d}" for i in range(1, 11)]
    assert rule(company, "order").next_value == 11


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_frozen_time_is_visible_in_threads(make_company):
    """time_machine патчит процесс целиком: потоки видят замороженный год (не текущий 2026)."""
    company, _, _ = make_company("ConcYear")
    with time_machine.travel(datetime(2030, 3, 1, tzinfo=dt_tz.utc), tick=False):
        results = _run_threads(company, 4, 2)
    assert sorted(results) == [f"ORD-2030-{i:05d}" for i in range(1, 5)]


# --- API ---

URL = "/api/numbering/"


def test_list_returns_all_rules_with_samples(admin_client):
    r = admin_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert [d["kind"] for d in data] == ALL_KINDS
    by = {d["kind"]: d for d in data}
    assert set(by["order"]) == {
        "kind",
        "name",
        "description",
        "template",
        "digits",
        "next_value",
        "sample",
    }
    assert by["order"]["name"] and by["order"]["description"]
    assert by["order"]["sample"] == "ORD-2026-00001"
    assert by["trip"]["sample"] == "ORD-2026-00001-1"
    assert by["consolidated_trip"]["sample"] == "C1"
    assert by["invoice_out"]["sample"] == "СЧ-2026-00001"
    assert by["invoice_in"]["sample"] == "ПС-2026-00001"


def test_sample_does_not_consume_counter(admin_client, company):
    admin_client.get(URL)
    admin_client.get(URL)
    assert rule(company, "order").next_value == 1
    assert num(company, "order") == "ORD-2026-00001"
    by = {d["kind"]: d for d in admin_client.get(URL).json()}
    assert by["order"]["sample"] == "ORD-2026-00002"
    assert by["trip"]["sample"] == "ORD-2026-00002-1"


def test_retrieve(admin_client):
    r = admin_client.get(f"{URL}order/")
    assert r.status_code == 200 and r.json()["kind"] == "order"
    assert admin_client.get(f"{URL}bogus/").status_code == 404


def test_patch_updates_rule(admin_client, company):
    r = admin_client.patch(
        f"{URL}order/",
        {"template": "З-{year}/{index}", "digits": 3, "next_value": 7},
        format="json",
    )
    assert r.status_code == 200
    assert r.json()["sample"] == "З-2026/007"
    assert num(company, "order") == "З-2026/007"
    assert admin_client.patch(f"{URL}order/", {"next_value": 1}, format="json").status_code == 200


def test_patch_cannot_change_kind(admin_client, company):
    admin_client.patch(f"{URL}order/", {"kind": "trip"}, format="json")
    assert rule(company, "order").kind == "order"


def test_no_create_delete_put(admin_client):
    assert admin_client.post(URL, {"kind": "order"}, format="json").status_code == 405
    assert admin_client.delete(f"{URL}order/").status_code == 405
    body = {"template": "{index}", "digits": 1, "next_value": 1}
    assert admin_client.put(f"{URL}order/", body, format="json").status_code == 405


@pytest.mark.parametrize(
    "kind,template",
    [
        ("order", "ORD-{year}"),  # нет {index}
        ("order", "ORD-{foo}-{index}"),  # неизвестный плейсхолдер
        ("order", "ORD-{index"),  # несбалансированные скобки
        ("order", "ORD-}{index}"),
        ("order", "{index!r}"),
        ("order", "{index:05d}"),
        ("order", "{}-{index}"),
        ("order", "{{index}}"),
        ("order", "{order}-{index}"),  # {order} не из контекста заказа
        ("order", ""),
        ("consolidated_trip", "C-{year}"),
        ("invoice_out", "СЧ"),
        ("invoice_in", "ПС"),
        ("trip", "{order}"),  # нет {n}
        ("trip", "{n}"),  # нет {order}
        ("trip", "{order}-{n}-{zzz}"),
    ],
)
def test_invalid_templates_rejected(admin_client, company, kind, template):
    before = rule(company, kind).template
    r = admin_client.patch(f"{URL}{kind}/", {"template": template}, format="json")
    assert r.status_code == 400, template
    assert rule(company, kind).template == before


@pytest.mark.parametrize(
    "body",
    [{"digits": -1}, {"digits": 11}, {"next_value": 0}, {"next_value": -5}, {"digits": "x"}],
)
def test_invalid_numbers_rejected(admin_client, body):
    assert admin_client.patch(f"{URL}order/", body, format="json").status_code == 400


def test_boundaries_accepted(admin_client):
    r = admin_client.patch(f"{URL}order/", {"digits": 0, "next_value": 1}, format="json")
    assert r.status_code == 200
    r = admin_client.patch(f"{URL}order/", {"digits": 10}, format="json")
    assert r.status_code == 200 and r.json()["sample"] == "ORD-2026-0000000001"


def test_trip_template_accepts_order_and_n(admin_client):
    r = admin_client.patch(f"{URL}trip/", {"template": "Рейс {n} по {order}"}, format="json")
    assert r.status_code == 200
    assert r.json()["sample"] == "Рейс 1 по ORD-2026-00001"


def test_valid_templates_never_raise_on_render(admin_client, company):
    admin_client.patch(f"{URL}order/", {"template": "{index}{year}{index}"}, format="json")
    assert num(company, "order") == "00001202600001"


def test_isolation_list_and_patch(make_company):
    a, _, client_a = make_company("A")
    b, _, client_b = make_company("B")
    r = client_b.patch(f"{URL}order/", {"template": "B-{index}", "next_value": 9}, format="json")
    assert r.status_code == 200
    assert rule(a, "order").template == "ORD-{year}-{index}" and rule(a, "order").next_value == 1
    assert (rule(b, "order").template, rule(b, "order").next_value) == ("B-{index}", 9)
    by_a = {d["kind"]: d for d in client_a.get(URL).json()}
    by_b = {d["kind"]: d for d in client_b.get(URL).json()}
    assert by_a["order"]["template"] == "ORD-{year}-{index}"
    assert by_b["order"]["template"] == "B-{index}"
    assert client_a.get(f"{URL}order/").json()["template"] == "ORD-{year}-{index}"
    assert client_b.get(f"{URL}order/").json()["next_value"] == 9
    # правка A не задевает B
    client_a.patch(f"{URL}order/", {"next_value": 42}, format="json")
    assert rule(b, "order").next_value == 9 and rule(a, "order").next_value == 42


def test_manager_cannot_patch_but_can_view_nothing_extra(make_company):
    company, _, _ = make_company("M")
    with tenant_context(company.id):
        role = Role.objects.get(name="Менеджер")
    user = User.objects.create_user(email="mgr@fixture.kz", password="s3cret-pass")
    Membership.objects.create(user=user, company=company, role=role, is_active=True)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert client.get(URL).status_code == 403  # у Менеджера нет numbering.view
    assert client.patch(f"{URL}order/", {"next_value": 5}, format="json").status_code == 403
    assert rule(company, "order").next_value == 1


def test_observer_can_view_but_not_patch(make_company):
    company, _, _ = make_company("O")
    with tenant_context(company.id):
        role = Role.objects.get(name="Наблюдатель")
    user = User.objects.create_user(email="obs@fixture.kz", password="s3cret-pass")
    Membership.objects.create(user=user, company=company, role=role, is_active=True)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert client.get(URL).status_code == 200
    assert client.patch(f"{URL}order/", {"next_value": 5}, format="json").status_code == 403


def test_readonly_subscription_blocks_patch(admin_client, company):
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get(URL).status_code == 200
    r = admin_client.patch(f"{URL}order/", {"next_value": 5}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "subscription_readonly"


def test_unauthenticated():
    assert APIClient().get(URL).status_code in (401, 403)
