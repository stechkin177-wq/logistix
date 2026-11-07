from django.core.management.base import BaseCommand, CommandError

from apps.core.tenancy import tenant_context
from apps.finance import migration
from apps.finance.errors import FinanceError
from apps.finance.models import FinanceMigrationIssue


class Command(BaseCommand):
    help = (
        "Ручное разрешение проблемы переноса. Для спорной строки (ambiguous_trip_expense) нужно "
        "решение: --resolution carrier_expense --trip ID|НОМЕР, --resolution manual_expense "
        "[--category КОД] или --resolution justified_exclusion (комментарий не короче 10 "
        "символов; сумма остаётся не отражённой в сверке и блокирует переключение)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--issue", type=int, required=True)
        parser.add_argument("--note", required=True)
        parser.add_argument("--resolution", choices=list(migration.RESOLUTIONS))
        parser.add_argument("--trip", help="id или номер рейса (для carrier_expense)")
        parser.add_argument("--category", help="код категории расходов (для manual_expense)")

    def handle(self, *args, issue, note, resolution, trip, category, **options):
        row = FinanceMigrationIssue.all_objects.filter(pk=issue).first()
        if row is None:
            raise CommandError(f"Проблема {issue} не найдена")
        params = {}
        if trip:
            params["trip"] = trip  # номер; цифры без совпадения по номеру трактуются как id
        if category:
            params["category"] = category
        try:
            with tenant_context(row.company_id):
                if (
                    trip
                    and trip.isdigit()
                    and not migration.Trip.objects.filter(number=trip).exists()
                ):
                    params["trip"] = int(trip)
                migration.resolve_issue(row, None, note, resolution, **params)
        except FinanceError as exc:
            raise CommandError(str(exc.detail)) from None
        self.stdout.write(f"Проблема #{issue} разрешена")
