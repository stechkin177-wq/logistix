# ruff: noqa: E501
import re

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Company
from apps.finance import reconcile


class Command(BaseCommand):
    help = (
        "Сверка старого учёта с новыми сущностями компании. Данные не меняются; результат - "
        "FinanceMigrationRun(kind=reconcile) и Issues reconcile_diff. Код возврата 0 всегда, статус в отчёте."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        parser.add_argument("--month", help="YYYY-MM: ограничить месячные проверки")

    def handle(self, *args, company, month, **options):
        if not Company.objects.filter(pk=company).exists():
            raise CommandError(f"Компания {company} не найдена")
        if month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise CommandError("Месяц в формате YYYY-MM")
        run = reconcile.reconcile(company, month=month)
        out = self.stdout.write
        s = run.summary
        out(
            f"Сверка финансов, запуск #{run.pk}: {run.status} (необъяснённых расхождений: {s['unexplained']})"
        )
        by_check: dict = {}
        for f in s["findings"]:
            by_check.setdefault(f["check"], []).append(f)
        for check in sorted(by_check):
            items = by_check[check]
            errors = [f for f in items if f["severity"] == "error"]
            out(f"  Проверка {check}: ошибок {len(errors)}, справочно {len(items) - len(errors)}")
            for f in items[:30]:
                out(f"    [{f['severity']}] {f['message']}")
        if s["legacy_missing"]:
            out(f"  legacy_missing (без курса, суммы НЕ исключены): {len(s['legacy_missing'])}")
        if s["not_reflected"]:
            out(
                f"  НЕ ОТРАЖЕНО в новой модели (суммы НЕ исключены из сверки): {len(s['not_reflected'])}"
            )
            for r in s["not_reflected"][:30]:
                out(
                    f"    строка #{r['line']} ({r['field']}) {r['amount']} {r['currency']} за {r['month']}: {r['reason']}"
                )
