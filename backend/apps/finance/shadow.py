"""Shadow-запись: зеркало изменений OrderService в новые Income / Expense / связи.

Активна ТОЛЬКО при settings.engine == 'shadow'. Чтение остаётся из старой системы. Зеркало =
migrate_order(order, overwrite=True) / migrate_invoice_links внутри ВЛОЖЕННОГО transaction.atomic()
(savepoint): ошибка зеркала откатывает только его, основная операция завершается как обычно, а
FinanceMigrationIssue(shadow_error) создаётся ПОСЛЕ отката во внешней транзакции. В engine='new'
действует обратное правило (ошибка прерывает операцию): это хуки 1.4.4-1.4.6, здесь не меняется.
"""

import logging

from django.db import transaction

from apps.core.tenancy import tenant_context
from apps.forwarding.models import Order

from . import migration
from .engine import company_engine, current_cid
from .models import FinanceMigrationIssue

logger = logging.getLogger(__name__)
ISSUE_TYPE = "shadow_error"


def is_shadow(company_id: int) -> bool:
    return company_engine(current_cid(company_id)) == "shadow"


def _record_error(cid: int, operation: str, label: str, exc: Exception) -> None:
    """Issue shadow_error вне savepoint зеркала; сбой записи Issue основную операцию не ломает."""
    try:
        with transaction.atomic(), tenant_context(cid):
            FinanceMigrationIssue.objects.create(
                company_id=cid,
                issue_type=ISSUE_TYPE,
                severity="error",
                source_model=label.split("#")[0],
                source_id=int(label.split("#")[1]) if "#" in label else None,
                message=f"Ошибка Shadow-зеркала: {operation}",
                details={"operation": operation, "object": label,
                         "error": f"{type(exc).__name__}: {str(exc)[:500]}"},
            )  # fmt: skip
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось записать shadow_error (%s %s)", operation, label)


def run_mirror(company_id: int, operation: str, label: str, fn) -> bool:
    """Выполняет зеркало в savepoint; True - зеркало применено (или shadow выключен)."""
    cid = current_cid(company_id)
    if company_engine(cid) != "shadow":
        return True
    try:
        with transaction.atomic(), tenant_context(cid):
            fn()
        return True
    except Exception as exc:  # noqa: BLE001
        _record_error(cid, operation, label, exc)
        return False


def mirror_order(order, operation: str) -> bool:
    def work():
        migration.migrate_order(Order.all_objects.get(pk=order.pk), overwrite=True)

    return run_mirror(order.company_id, operation, f"forwarding.order#{order.pk}", work)


def before_line_delete(line) -> bool:
    """ДО удаления строки: зеркало отвязывается (Income void, доля снята), без ProtectedError."""
    return run_mirror(
        line.company_id,
        "order_line_delete",
        f"forwarding.orderservice#{line.pk}",
        lambda: migration.detach_line(line),
    )


def mirror_invoice(invoice, operation: str) -> bool:
    return run_mirror(
        invoice.company_id,
        operation,
        f"finance.invoice#{invoice.pk}",
        lambda: migration.migrate_invoice_links(invoice),
    )
