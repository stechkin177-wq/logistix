"""Встроенные поставщики документов: семь прежних видов без изменения поведения.

Договор, заявка, договор-заявка перевозчику и CMR принадлежат модулю forwarding, акт и счёт на
оплату - модулю finance (письмо, как и прочие, остаётся видом forwarding). Файл не импортирует
модели других приложений: загрузку и блокировку исходных записей по-прежнему делает
documents.services.issue_document (прежний путь), а здесь только таблица соответствий
вид -> субъект и права. Контекст по-прежнему строит documents.context.build_context.
"""

from .providers import DocumentProvider, register_provider

# вид -> (subject_type, аргумент выдачи, право на источник)
FORWARDING_KINDS = {
    "contract": ("forwarding.client", "client", "clients.view"),
    "order_request": ("forwarding.order", "order", "orders.view"),
    "carrier_order": ("forwarding.trip", "trip", "trips.view"),
    "cmr": ("forwarding.trip", "trip", "trips.view"),
    "letter": ("forwarding.order", "order", None),
}
FINANCE_KINDS = {
    "act": ("finance.invoice", "invoice", "finance.view"),
    "invoice_print": ("finance.invoice", "invoice", "finance.view"),
}
KIND_TO_SUBJECT = {**FORWARDING_KINDS, **FINANCE_KINDS}


class _BuiltinProvider(DocumentProvider):
    table: dict = {}

    def __init__(self):
        self.kinds = tuple(self.table)
        self.subject_types = tuple(dict.fromkeys(v[0] for v in self.table.values()))

    def required_permission(self, kind: str) -> str | None:
        return self.table[kind][2]

    def build_context(self, kind: str, subject, language: str) -> dict:
        raise NotImplementedError("Встроенные виды строит documents.services.issue_document")

    def load_subject(self, subject_type: str, subject_id: int):
        raise NotImplementedError("Встроенные виды выдаются прежним путём (issue_document)")


class ForwardingDocumentProvider(_BuiltinProvider):
    module_code = "forwarding"
    table = FORWARDING_KINDS


class FinanceDocumentProvider(_BuiltinProvider):
    module_code = "finance"
    table = FINANCE_KINDS


def module_of_kind(kind: str) -> str:
    return "finance" if kind in FINANCE_KINDS else "forwarding"


def subject_of(kind: str, links: dict) -> tuple[str, int] | None:
    """Пара (subject_type, subject_id) прежнего вида по найденным ссылкам; None - субъекта нет."""
    subject_type, arg, _ = KIND_TO_SUBJECT[kind]
    obj = links.get(arg)
    return (subject_type, obj.pk) if obj is not None else None


FORWARDING_PROVIDER = ForwardingDocumentProvider()
FINANCE_PROVIDER = FinanceDocumentProvider()


def register_builtin_providers() -> None:
    register_provider(FORWARDING_PROVIDER)
    register_provider(FINANCE_PROVIDER)
