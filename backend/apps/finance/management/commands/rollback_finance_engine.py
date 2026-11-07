# ruff: noqa: E501
from django.core.management.base import BaseCommand, CommandError

from apps.finance import switching
from apps.finance.errors import FinanceError


class Command(BaseCommand):
    help = (
        "Откат engine=new -> shadow|legacy (решение заказчика E): не более 30 дней, нет записей, "
        "которых нельзя представить в старой модели, полная сверка успешна, есть ссылка на "
        "разрешение. НИЧЕГО не удаляет, только возвращает engine."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        parser.add_argument("--to", choices=["shadow", "legacy"], required=True)
        parser.add_argument("--approval-ref", default="")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, company, to, approval_ref, dry_run, **options):
        try:
            result = switching.rollback_engine(
                company, to, approval_ref=approval_ref, dry_run=dry_run
            )
        except switching.SwitchRefused as exc:
            lines = "\n".join(f"  - [{r['code']}] {r['message']}" for r in exc.reasons)
            raise CommandError(f"Откат отклонён:\n{lines}") from None
        except FinanceError as exc:
            raise CommandError(str(exc.detail)) from None
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(f"{prefix}Компания {company}: {result['from']} -> {result['to']}")
