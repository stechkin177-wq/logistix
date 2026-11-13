from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.audit.models import AuditLog
from apps.core.audit.services import LOGIN_ACTIONS
from apps.core.models import Company
from apps.core.tenancy import tenant_context


class Command(BaseCommand):
    help = (
        "Удаляет события входа (login, login_failed) старше срока хранения компании "
        "(Company.login_audit_retention_days, по умолчанию 90 дней). Остальные записи журнала "
        "не затрагиваются. Это единственный разрешённый путь удаления из журнала аудита."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="только посчитать")

    def handle(self, *args, **options):
        now = timezone.now()
        total = 0
        for company in Company.objects.all():
            border = now - timedelta(days=company.login_audit_retention_days)
            with tenant_context(company.id):
                qs = AuditLog.objects.filter(action__in=LOGIN_ACTIONS, created_at__lt=border)
                count = qs.count()
                if count and not options["dry_run"]:
                    # queryset.delete() идёт на уровне SQL: защита экземпляров не мешает
                    qs.delete()
            total += count
            if count:
                days = company.login_audit_retention_days
                self.stdout.write(f"{company.name}: {count} (старше {days} дн.)")
        verb = "найдено" if options["dry_run"] else "удалено"
        self.stdout.write(f"Событий входа {verb}: {total}")
