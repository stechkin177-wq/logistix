"""Защита от пулеров PgBouncer (транзакционный/операторный режим): RLS опирается на
сессионный GUC app.company_id, поэтому такой пулер - утечка данных между компаниями."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.dbguard import check_database_url, pooler_problem

DENIED = [
    "postgresql://u:p@ep-cool-123-pooler.c-2.eu-central-1.aws.neon.tech/db?sslmode=require",
    "postgres://u:p@EP-X-POOLER.eu-central-1.aws.neon.tech:5432/db",
    "postgresql://postgres.abc:p@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
    "postgresql://u:p@db.example.com:6543/db",
    "postgresql://u:p@db.example.com:5432/db?pgbouncer=true",
    "postgresql://u:p@db.example.com:5432/db?sslmode=require&pgbouncer=TRUE",
    "postgresql://u:p@db.example.com:5432/db?pgbouncer=1",
    "postgresql://u:p@db.example.com:6432/db",
    "postgresql://u:p@db.example.com:5432/db?host=other.example.com",
    "postgresql://u:p@db.example.com:5432/db?hostaddr=10.0.0.1",
    "postgresql://u:p@db.example.com/db?sslmode=require&HOST=/tmp",
]
UNPARSABLE = [
    "postgresql://u:p@h1:5432,h2:5432/db",
    "postgresql://u:p@db.example.com:99999/db",
    "postgresql://u:p@db.example.com:abc/db",
    "postgresql://u:p@[::1/db",
    "not a url at all",
    "postgresql:///db",
]
ALLOWED = [
    "postgresql://u:p@ep-cool-123.c-2.eu-central-1.aws.neon.tech/db?sslmode=require",
    "postgresql://postgres.abc:p@aws-0-eu-central-1.pooler.supabase.com:5432/postgres",
    "postgres://logistix:logistix@127.0.0.1:5432/logistix",
    "postgres://logistix:logistix@db:5432/logistix",
    "postgresql://u:p@db.example.com/db?pgbouncer=false",
    "",
]


@pytest.mark.parametrize("url", DENIED)
def test_pooler_urls_detected(url):
    assert pooler_problem(url)


@pytest.mark.parametrize("url", ALLOWED)
def test_direct_and_session_urls_allowed(url):
    assert pooler_problem(url) is None


def test_message_does_not_leak_password():
    url = "postgresql://u:SuperSecretPw@ep-a-pooler.neon.tech/db"
    assert "SuperSecretPw" not in pooler_problem(url)


@pytest.mark.parametrize("url", DENIED)
def test_serverless_rejects_pooler_even_with_pooler_ok(url):
    with pytest.raises(ImproperlyConfigured, match="пулер"):
        check_database_url(url, serverless=True, debug=True, pooler_ok=True)


@pytest.mark.parametrize("url", DENIED)
def test_production_rejects_pooler_without_ack(url):
    with pytest.raises(ImproperlyConfigured, match="DATABASE_POOLER_OK"):
        check_database_url(url, serverless=False, debug=False, pooler_ok=False)


def test_production_allows_pooler_with_explicit_ack():
    check_database_url(DENIED[0], serverless=False, debug=False, pooler_ok=True)


def test_debug_non_serverless_not_checked():
    check_database_url(DENIED[0], serverless=False, debug=True, pooler_ok=False)


def test_allowed_urls_pass_in_serverless():
    for url in ALLOWED:
        check_database_url(url, serverless=True, debug=False, pooler_ok=False)


@pytest.mark.parametrize("url", UNPARSABLE)
def test_unparsable_fails_closed_when_guard_active(url):
    for kwargs in (
        {"serverless": True, "debug": True, "pooler_ok": True},
        {"serverless": False, "debug": False, "pooler_ok": False},
    ):
        with pytest.raises(ImproperlyConfigured, match="разобрать") as exc:
            check_database_url(url, **kwargs)
        assert "SuperSecret" not in str(exc.value) and url not in str(exc.value)


@pytest.mark.parametrize("url", UNPARSABLE)
def test_unparsable_not_checked_when_guard_inactive(url):
    check_database_url(url, serverless=False, debug=True, pooler_ok=False)
    check_database_url(url, serverless=False, debug=False, pooler_ok=True)


def test_unparsable_message_has_no_password():
    url = "postgresql://u:SuperSecretPw@h1:5432,h2:5432/db"
    with pytest.raises(ImproperlyConfigured) as exc:
        check_database_url(url, serverless=True, debug=False, pooler_ok=False)
    assert "SuperSecretPw" not in str(exc.value)
