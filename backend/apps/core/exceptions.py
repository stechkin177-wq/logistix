from rest_framework.exceptions import ErrorDetail
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """Формат ошибок API: {"detail": "...", "code": "..."} для ошибок с одним detail."""
    response = exception_handler(exc, context)
    payload = getattr(exc, "payload", None)  # исключения с собственным телом (лимиты тарифа)
    if response is not None and isinstance(payload, dict):
        response.data = payload
        return response
    if response is not None and isinstance(response.data, dict):
        detail = response.data.get("detail")
        if isinstance(detail, ErrorDetail) and "code" not in response.data:
            response.data["code"] = detail.code
    return response
