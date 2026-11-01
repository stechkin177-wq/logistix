"""Sentry: включается только при заданном SENTRY_DSN. DSN должен указывать на собственный
(в Казахстане) Sentry либо быть пустым - персональные данные не покидают страну."""

import os

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-csrftoken"}


def scrub_event(event, hint=None):
    """before_send: убирает тело запроса, cookie и Authorization."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                k: v for k, v in headers.items() if str(k).lower() not in SENSITIVE_HEADERS
            }
    event.pop("user", None)
    return event


def init_sentry(dsn=None, environment=None, traces_sample_rate=None):
    dsn = dsn if dsn is not None else os.environ.get("SENTRY_DSN", "")
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment or os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=(
            traces_sample_rate
            if traces_sample_rate is not None
            else float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0"))
        ),
        send_default_pii=False,
        max_request_body_size="never",
        before_send=scrub_event,
    )
    return True
