from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.handbooks.status_codes import SPECS_BY_HANDBOOK, TRIP_STATUS
from apps.core.handbooks.system_codes import SYSTEM_CODES, system_code_assignment
from apps.core.models import Company
from apps.core.tenancy import tenant_context

ASSIGNABLE = (TRIP_STATUS,)


class Command(BaseCommand):
    help = (
        "Ручное назначение системного кода статуса рейса значению компании (владелец платформы). "
        "Проверки: код из реестра trip_status, значение принадлежит справочнику trip_status этой "
        "компании и не имеет кода, код не занят. Пишет запись аудита. --dry-run ничего не пишет."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True, help="ID компании")
        parser.add_argument("--value", type=int, required=True, help="ID значения справочника")
        parser.add_argument("--code", required=True, help="Системный код, например COMPLETED")
        parser.add_argument("--dry-run", action="store_true", help="Только проверить")

    def handle(self, *args, **options):
        code = options["code"]
        company = Company.objects.filter(pk=options["company"]).first()
        if company is None:
            raise CommandError(f"Компания {options['company']} не найдена")
        if code not in SYSTEM_CODES[TRIP_STATUS]:
            allowed = ", ".join(sorted(SYSTEM_CODES[TRIP_STATUS]))
            raise CommandError(f"Код {code!r} не входит в реестр trip_status: {allowed}")
        with tenant_context(company.id), transaction.atomic():
            value = (
                HandbookValue.objects.select_related("handbook")
                .select_for_update(of=("self",))
                .filter(pk=options["value"])
                .first()
            )
            if value is None:
                raise CommandError(
                    f"Значение {options['value']} не найдено в компании {company.id}"
                )
            if value.handbook.code not in ASSIGNABLE:
                raise CommandError("Значение не из справочника trip_status")
            if value.code == code:
                self.stdout.write(f"Значение #{value.pk} уже имеет код {code}: ничего не меняется")
                return
            if value.code:
                raise CommandError(f"У значения уже есть код {value.code!r}; менять код нельзя")
            holder = HandbookValue.objects.filter(handbook=value.handbook, code=code).first()
            if holder is not None:
                raise CommandError(f"Код {code} уже занят значением #{holder.pk} «{holder.name}»")
            spec = next(s for s in SPECS_BY_HANDBOOK[value.handbook.code] if s.code == code)
            if (value.is_initial, value.is_final) != (spec.is_initial, spec.is_final):
                self.stdout.write(
                    self.style.WARNING(
                        f"Внимание: признаки значения (начальное={value.is_initial}, "
                        f"конечное={value.is_final}) отличаются от стандартных для {code} "
                        f"(начальное={spec.is_initial}, конечное={spec.is_final})"
                    )
                )
            if options["dry_run"]:
                self.stdout.write(
                    f"[dry-run] Значению #{value.pk} «{value.name}» будет назначен код {code}"
                )
                return
            with system_code_assignment():
                value.code = code
                value.save(update_fields=["code"])
            audit.log(
                "update",
                value,
                None,
                {"code": ["", code], "source": "assign_system_status_code"},
            )
            self.stdout.write(f"Значению #{value.pk} «{value.name}» назначен код {code}")
