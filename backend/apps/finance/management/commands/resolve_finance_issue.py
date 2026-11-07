from django.core.management.base import BaseCommand, CommandError

from apps.core.tenancy import tenant_context
from apps.finance import migration
from apps.finance.errors import FinanceError
from apps.finance.models import FinanceMigrationIssue


class Command(BaseCommand):
    help = "Ручное разрешение спорной строки переноса: Issue -> resolved (комментарий обязателен)."

    def add_arguments(self, parser):
        parser.add_argument("--issue", type=int, required=True)
        parser.add_argument("--note", required=True)

    def handle(self, *args, issue, note, **options):
        row = FinanceMigrationIssue.all_objects.filter(pk=issue).first()
        if row is None:
            raise CommandError(f"Проблема {issue} не найдена")
        try:
            with tenant_context(row.company_id):
                migration.resolve_issue(row, None, note)
        except FinanceError as exc:
            raise CommandError(str(exc.detail)) from None
        self.stdout.write(f"Проблема #{issue} разрешена")
