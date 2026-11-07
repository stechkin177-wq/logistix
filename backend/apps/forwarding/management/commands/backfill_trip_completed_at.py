from django.core.management.base import BaseCommand, CommandError

from apps.core.audit.models import AuditLog
from apps.core.models import Company
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Trip
from apps.forwarding.trips.services import COMPLETED_CODE


def last_completion_times(company: Company, trips: list[Trip]) -> dict[int, object]:
    """{id рейса: время последней записи аудита update с переходом в его текущий статус}.

    Только аудит forwarding.trip; резервные источники (Order.completed_at) не используются.
    """
    wanted = {str(t.pk): t for t in trips}
    found: dict[int, object] = {}
    rows = AuditLog.objects.filter(
        company=company,
        action="update",
        object_type="forwarding.trip",
        object_id__in=list(wanted),
    ).order_by("-created_at", "-id")
    for row in rows.iterator():
        trip = wanted[row.object_id]
        if trip.pk in found:
            continue
        change = row.changes.get("status_id") if isinstance(row.changes, dict) else None
        if isinstance(change, list) and len(change) == 2 and change[1] == trip.status_id:
            found[trip.pk] = row.created_at
    return found


class Command(BaseCommand):
    help = (
        "Заполняет Trip.completed_at у рейсов в статусе COMPLETED с пустым значением по времени "
        "последней записи аудита с переходом в этот статус. Если записи нет - время не "
        "придумывается, рейс попадает в отчёт «требует проверки». Идемпотентна."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, help="ID компании (по умолчанию все)")
        parser.add_argument("--dry-run", action="store_true", help="Только отчёт, без записи")

    def handle(self, *args, **options):
        companies = Company.objects.order_by("id")
        if options["company"] is not None:
            companies = companies.filter(pk=options["company"])
            if not companies.exists():
                raise CommandError(f"Компания {options['company']} не найдена")
        dry = options["dry_run"]
        prefix = "[dry-run] " if dry else ""
        total_set = total_review = 0
        for company in companies:
            with tenant_context(company.id):
                trips = list(
                    Trip.all_objects.filter(
                        company=company,
                        completed_at__isnull=True,
                        status__handbook__code="trip_status",
                        status__code=COMPLETED_CODE,
                    ).order_by("pk")
                )
                found = last_completion_times(company, trips) if trips else {}
                review = []
                for trip in trips:
                    when = found.get(trip.pk)
                    if when is None:
                        review.append(trip)
                        continue
                    if not dry:
                        # update(): updated_at и прочие поля рейса не затрагиваются
                        Trip.all_objects.filter(pk=trip.pk, completed_at__isnull=True).update(
                            completed_at=when
                        )
            self.stdout.write(
                f"{prefix}Компания #{company.id} {company.name}: "
                f"{'будет заполнено' if dry else 'заполнено'} {len(found)}, "
                f"требует проверки {len(review)}"
            )
            for trip in review:
                self.stdout.write(
                    f"  требует проверки: рейс #{trip.pk} {trip.number} "
                    "(нет записи аудита о переходе в «Завершён»)"
                )
            total_set += len(found)
            total_review += len(review)
        self.stdout.write(
            f"{prefix}Итого: {'будет заполнено' if dry else 'заполнено'} {total_set}, "
            f"требует проверки {total_review}"
        )
