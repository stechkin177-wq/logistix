import tempfile
from pathlib import Path

from .settings import *  # noqa: F401,F403
from .settings import INSTALLED_APPS

# Тестовые конкретные модели (apps/core/tests/models.py); в продакшене не подключаются.
INSTALLED_APPS = [*INSTALLED_APPS, "apps.core.tests.apps.CoreTestsConfig"]
MIGRATION_MODULES = {"core_tests": "apps.core.tests.migrations"}

# Загрузки тестов - во временный каталог, не в репозиторий
MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="logistix-test-media-"))
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
