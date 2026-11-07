from django.core.management.base import BaseCommand, CommandError

from apps.finance import switching
from apps.finance.errors import FinanceError


class Command(BaseCommand):
    help = (
        "Безопасная остановка финансовых изменений компании: при --on все финансовые записи "
        "отвечают 423 finance_frozen, чтение работает. --off снимает остановку."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--on", action="store_true")
        group.add_argument("--off", action="store_true")
        parser.add_argument("--reason", required=True)

    def handle(self, *args, company, on, off, reason, **options):
        try:
            switching.set_frozen(company, bool(on), reason=reason)
        except FinanceError as exc:
            raise CommandError(str(exc.detail)) from None
        self.stdout.write(
            f"Компания {company}: финансовые изменения {'заморожены' if on else 'разморожены'}"
        )
