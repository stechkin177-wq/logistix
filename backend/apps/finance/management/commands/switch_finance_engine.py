# ruff: noqa: E501
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.finance import switching
from apps.finance.errors import FinanceError


class Command(BaseCommand):
    help = (
        "Переключение режима учёта компании: legacy -> shadow, shadow -> new. Для new проверяются "
        "ВСЕ условия (shadow, cutover, сопоставление статусов, сверка, нет открытых error-проблем и "
        "не отражённых сумм, нет заморозки, ссылка на разрешение заказчика). --dry-run ничего не "
        "пишет. НЕ запускать против реальных компаний без отдельного разрешения заказчика."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        parser.add_argument("--to", choices=["shadow", "new"], required=True)
        parser.add_argument("--cutover", help="YYYY-MM-DD (обязательно для new)")
        parser.add_argument("--approval-ref", default="", help="Ссылка на разрешение заказчика")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, company, to, cutover, approval_ref, dry_run, **options):
        cut = None
        if cutover:
            try:
                cut = date.fromisoformat(cutover)
            except ValueError:
                raise CommandError("Дата cutover в формате YYYY-MM-DD") from None
        try:
            if to == "shadow":
                result = switching.switch_to_shadow(
                    company, approval_ref=approval_ref, dry_run=dry_run
                )
            else:
                result = switching.switch_to_new(
                    company, cutover=cut, approval_ref=approval_ref, dry_run=dry_run
                )
        except switching.SwitchRefused as exc:
            lines = "\n".join(f"  - [{r['code']}] {r['message']}" for r in exc.reasons)
            raise CommandError(f"Переключение отклонено:\n{lines}") from None
        except FinanceError as exc:
            raise CommandError(str(exc.detail)) from None
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(f"{prefix}Компания {company}: {result['from']} -> {result['to']}")
        for key, value in result.get("changes", {}).items():
            self.stdout.write(f"  {key}: {value}")
