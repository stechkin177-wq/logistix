# ruff: noqa: E501
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import Company
from apps.core.tenancy import tenant_context
from apps.finance import migration
from apps.finance.income import get_settings_for
from apps.finance.models import (
    ExpenseAllocation,
    FinanceMigrationIssue,
    FinanceMigrationRun,
    Income,
    Invoice,
)
from apps.forwarding.models import Order


def created_sums(company_id: int) -> dict:
    """Суммы перенесённых объектов по (валюта, месяц) - для сравнения с суммами источников."""
    out: dict = {}
    for inc in (
        Income.objects.filter(legacy_line__isnull=False)
        .exclude(status="void")
        .select_related("currency")
    ):
        bucket = out.setdefault(inc.currency.code, {}).setdefault(
            f"{inc.recognized_on:%Y-%m}", {"income": 0, "expense": 0}
        )
        bucket["income"] += inc.amount
    for al in ExpenseAllocation.objects.filter(legacy_line__isnull=False).select_related(
        "expense__currency", "legacy_line"
    ):
        bucket = out.setdefault(al.expense.currency.code, {}).setdefault(
            f"{al.legacy_line.date:%Y-%m}", {"income": 0, "expense": 0}
        )
        bucket["expense"] += al.amount
    return {
        c: {m: {k: str(v) for k, v in b.items()} for m, b in sorted(ms.items())}
        for c, ms in sorted(out.items())
    }


class Command(BaseCommand):
    help = (
        "Переносит строки OrderService компании в Income/Expense/доли и связи со счетами. "
        "Только для engine legacy/shadow. --dry-run ничего не пишет (кроме записи Run)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, company, dry_run, **options):
        company_obj = Company.objects.filter(pk=company).first()
        if company_obj is None:
            raise CommandError(f"Компания {company} не найдена")
        with tenant_context(company):
            engine = get_settings_for(company).engine
            if engine == "new":
                raise CommandError("Перенос недоступен для компании с engine=new")
            run = FinanceMigrationRun.objects.create(
                company_id=company, kind="migrate", mode="dry_run" if dry_run else "apply",
                params={"company": company, "engine": engine, "dry_run": dry_run},
            )  # fmt: skip
            result = migration.Result()
            link_counters = migration.Counter()
            for order in Order.all_objects.filter(company_id=company).order_by("pk"):
                try:
                    with transaction.atomic():
                        result.merge(migration.migrate_order(order, run=run, dry_run=dry_run))
                except Exception as exc:  # noqa: BLE001 - ошибка заказа не останавливает перенос
                    result.counters["order_errors"] += 1
                    if not dry_run:
                        FinanceMigrationIssue.objects.create(
                            company_id=company, run=run, issue_type="migrate_error", severity="error",
                            source_model="forwarding.order", source_id=order.pk,
                            message=f"Ошибка переноса заказа: {type(exc).__name__}: {str(exc)[:300]}",
                        )  # fmt: skip
            for invoice in Invoice.objects.exclude(status="cancelled").order_by("pk"):
                try:
                    with transaction.atomic():
                        link_counters.update(
                            migration.migrate_invoice_links(invoice, dry_run=dry_run)
                        )
                except Exception as exc:  # noqa: BLE001
                    result.counters["invoice_errors"] += 1
                    if not dry_run:
                        FinanceMigrationIssue.objects.create(
                            company_id=company, run=run, issue_type="migrate_error", severity="error",
                            source_model="finance.invoice", source_id=invoice.pk,
                            message=f"Ошибка связей счёта: {type(exc).__name__}: {str(exc)[:300]}",
                        )  # fmt: skip
            result.counters.update(link_counters)
            open_issues = FinanceMigrationIssue.objects.filter(
                status="open", severity="error", issue_type__in=migration.MIGRATION_ISSUE_TYPES
            ).count()
            run.summary = {
                "counters": dict(result.counters),
                "source": result.sources_json(),
                "created": {} if dry_run else created_sums(company),
                "disputed_lines": result.issues,
                "open_issues": open_issues,
            }
            run.finished_at = timezone.now()
            run.status = (
                "success"
                if open_issues == 0 and not result.counters["order_errors"]
                else "needs_review"
            )
            run.save()
            self._print(run, result, dry_run)

    def _print(self, run, result, dry_run):
        out = self.stdout.write
        out(("[dry-run] " if dry_run else "") + f"Перенос финансов, запуск #{run.pk}: {run.status}")
        for key, value in sorted(result.counters.items()):
            out(f"  {key}: {value}")
        for issue in result.issues:
            out(
                f"  СПОРНО: строка #{issue['line']} заказа #{issue['order']} «{issue['title']}»: {issue['message']}"
            )
        out(f"  Открытых проблем (error): {run.summary['open_issues']}")
