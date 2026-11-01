from rest_framework.exceptions import APIException


class DocumentError(APIException):
    """Ошибка операции с документами: ответ {"detail": "...", "code": "<code>"}."""

    status_code = 400

    def __init__(self, code: str, detail: str, status_code: int | None = None):
        super().__init__(detail=detail, code=code)
        if status_code is not None:
            self.status_code = status_code
