import importlib

import pytest
from django.test import override_settings
from django.urls import clear_url_caches, resolve
from django.urls.exceptions import Resolver404


@pytest.fixture
def reload_urls():
    yield
    import config.urls

    clear_url_caches()
    importlib.reload(config.urls)


def test_admin_route_can_be_disabled(reload_urls):
    import config.urls

    with override_settings(ADMIN_ENABLED=False):
        importlib.reload(config.urls)
        clear_url_caches()
        with pytest.raises(Resolver404):
            resolve("/admin/login/", urlconf="config.urls")
        assert resolve("/api/health/", urlconf="config.urls")


def test_admin_route_enabled_by_default(reload_urls):
    import config.urls

    with override_settings(ADMIN_ENABLED=True):
        importlib.reload(config.urls)
        clear_url_caches()
        assert resolve("/admin/login/", urlconf="config.urls")
