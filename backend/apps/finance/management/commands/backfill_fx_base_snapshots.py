from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Company
from apps.finance import backfill


class Command(BaseCommand):
    help = (
        "Заполняет снимки курса к базовой валюте (base_currency/rate_to_base/rate_to_base_date) у "
        "прежних счетов и оплат ТОЛЬКО в детерминированном случае: база компании = KZT и есть "
        "rate_to_kzt (копия). Остальные записи не трогает. Идемпотентно; --dry-run ничего не пишет."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, company, dry_run, **options):
        if not Company.objects.filter(pk=company).exists():
            raise CommandError(f"Компания {company} не найдена")
        r = backfill.backfill_company(company, dry_run=dry_run)
        mode = "ПРОБНЫЙ ЗАПУСК (ничего не записано)" if dry_run else "ПРИМЕНЕНО"
        self.stdout.write(f"Компания {company}: {mode}; базовая валюта: {r['base'] or 'не задана'}")
        if not r["applicable"]:
            self.stdout.write(
                "Детерминированный случай не применим (база не KZT): записи не изменены, остаются "
                "«без базового курса»"
            )
        self.stdout.write(
            f"Счета: {'заполнено' if not dry_run else 'будет заполнено'} {r['invoices']}, "
            f"остаются без снимка {r['skipped_invoices']}"
        )
        self.stdout.write(
            f"Оплаты: {'заполнено' if not dry_run else 'будет заполнено'} {r['payments']}, "
            f"остаются без снимка {r['skipped_payments']}"
        )
