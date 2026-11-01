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
