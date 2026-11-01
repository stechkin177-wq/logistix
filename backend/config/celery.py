import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.observability import init_sentry  # noqa: E402

init_sentry()

app = Celery("logistix")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
