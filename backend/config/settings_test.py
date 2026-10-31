from .settings import *  # noqa: F401,F403
from .settings import INSTALLED_APPS

# Тестовые конкретные модели (apps/core/tests/models.py); в продакшене не подключаются.
INSTALLED_APPS = [*INSTALLED_APPS, "apps.core.tests"]
MIGRATION_MODULES = {"tests": "apps.core.tests.migrations"}
