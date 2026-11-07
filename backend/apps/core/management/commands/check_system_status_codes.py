from django.core.management.base import BaseCommand, CommandError

from apps.core.handbooks.models import HandbookValue
from apps.core.handbooks.status_codes import analyze
from apps.core.handbooks.system_codes import SYSTEM_CODES
from apps.core.models import Company
from apps.core.tenancy import tenant_context


def collect_report(company: Company) -> dict:
    """{handbook_code: [CodeReport]} по справочникам реестра системных кодов; ничего не пишет."""
    result = {}
    with tenant_context(company.id):
        for handbook_code, codes in SYSTEM_CODES.items():
            rows = list(
                HandbookValue.objects.filter(handbook__code=handbook_code)
                .order_by("order", "id")
                .values("id", "name", "code", "is_initial", "is_final")
            )
            result[handbook_code] = (analyze(handbook_code, codes, rows), rows)
    return result


class Command(BaseCommand):
    help = (
        "Отчёт ручной проверки системных кодов статусов: по каждой компании какие коды назначены, "
        "каких нет, кандидаты и неоднозначности. Ничего не меняет, код возврата 0."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, help="ID компании (по умолчанию все)")

    def handle(self, *args, **options):
        companies = Company.objects.order_by("id")
        if options["company"] is not None:
            companies = companies.filter(pk=options["company"])
            if not companies.exists():
                raise CommandError(f"Компания {options['company']} не найдена")
        problems = 0
        for company in companies:
            self.stdout.write(f"Компания #{company.id} {company.name}")
            for handbook_code, (reports, rows) in collect_report(company).items():
                self.stdout.write(f"  Справочник {handbook_code}:")
                names = {r["id"]: r["name"] for r in rows}
                for rep in reports:
                    if rep.assigned:
                        self.stdout.write(
                            f"    {rep.code}: назначен (значение #{rep.value_id} "
                            f"«{names[rep.value_id]}»)"
                        )
                        continue
                    problems += 1
                    if rep.assign_to is not None:
                        self.stdout.write(
                            f"    {rep.code}: НЕ назначен; однозначное совпадение - значение "
                            f"#{rep.assign_to} «{names[rep.assign_to]}» (повторите миграцию "
                            "или назначьте командой assign_system_status_code)"
                        )
                    else:
                        self.stdout.write(f"    {rep.code}: НЕ назначен; требует ручной проверки")
                        self.stdout.write(f"      причина: {rep.reason}")
                    for cand in rep.candidates:
                        self.stdout.write(
                            f"      кандидат: #{cand['id']} «{cand['name']}» "
                            f"(начальное={cand['is_initial']}, конечное={cand['is_final']})"
                        )
        self.stdout.write(
            f"Итого кодов без значения: {problems}" if problems else "Все системные коды назначены."
        )
