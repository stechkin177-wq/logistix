from django.core.management.base import BaseCommand, CommandError

from apps.billing import events
from apps.billing.models import BillingEvent
from apps.core.models import PLATFORM_ADMIN, PLATFORM_OWNER, User
from apps.core.phone import normalize_phone


class Command(BaseCommand):
    help = (
        "Назначить/снять платформенную роль существующему пользователю: "
        "set_platform_role <email|телефон> owner|admin|none. "
        "Superuser Django ролью не наделяется автоматически."
    )

    def add_arguments(self, parser):
        parser.add_argument("login")
        parser.add_argument("role", choices=[PLATFORM_OWNER, PLATFORM_ADMIN, "none"])

    def handle(self, *args, login, role, **options):
        field = "email" if "@" in login else "phone"
        value = login.strip().lower() if field == "email" else normalize_phone(login)
        user = User.objects.filter(**{field: value}).first()
        if user is None:
            raise CommandError("Пользователь не найден")
        new = "" if role == "none" else role
        before, user.platform_role = user.platform_role, new
        user.save(update_fields=["platform_role"])
        events.record(
            BillingEvent.AUTH, user.pk, "platform_role", {"platform_role": [before, new]}, None
        )
        self.stdout.write(f"{value}: платформенная роль {before or '-'} -> {new or '-'}")
