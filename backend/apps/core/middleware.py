class TenantContextMiddleware:
    """Оборачивает запрос в tenant_context(None).

    Аутентификатор DRF выставляет компанию уже внутри view; при выходе из блока
    значение сбрасывается всегда (в том числе при исключении), поэтому между
    запросами в одном потоке/контексте компания не протекает.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .tenancy import tenant_context

        with tenant_context(None):
            return self.get_response(request)
