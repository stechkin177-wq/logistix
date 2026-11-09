import itertools

import pytest
from rest_framework.test import APIClient

from apps.core.api.auth import issue_tokens
from apps.core.models import User
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import set_current_company

TEST_PASSWORD = "s3cret-pass"
_counter = itertools.count(1)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def make_company(db):
    """Фабрика: (компания, администратор, авторизованный клиент) с ролями, юрлицом и подпиской."""

    def factory(name=None, modules=None):
        n = next(_counter)
        admin = User.objects.create_user(email=f"admin{n}@fixture.kz", password=TEST_PASSWORD)
        company = create_company_with_defaults(
            name or f"Company {n}", admin, modules or ["forwarding"]
        )
        client = APIClient()
        tokens = issue_tokens(admin, company.id)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        set_current_company(None)
        return company, admin, client

    yield factory
    set_current_company(None)


@pytest.fixture
def _default_company(make_company):
    return make_company("Fixture Co")


@pytest.fixture
def company(_default_company):
    return _default_company[0]


@pytest.fixture
def admin_user(_default_company):
    return _default_company[1]


@pytest.fixture
def admin_client(_default_company):
    return _default_company[2]


@pytest.fixture
def make_platform_client(db):
    """Фабрика: (клиент с ПЛАТФОРМЕННЫМ токеном, пользователь). Аккаунт без членства в компаниях."""

    def factory(role="owner"):
        n = next(_counter)
        user = User.objects.create_user(
            email=f"platform{n}@fixture.kz", password=TEST_PASSWORD, platform_role=role
        )
        client = APIClient()
        tokens = issue_tokens(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        return client, user

    return factory


@pytest.fixture
def platform_api(make_platform_client, _default_company):
    """Клиент владельца платформы (платформенный контекст)."""
    return make_platform_client("owner")[0]
