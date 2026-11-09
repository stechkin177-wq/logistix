from django.core.management.base import BaseCommand, CommandError

from apps.billing import events
from apps.billing.models import BillingEvent
from apps.core.models import User, token_clock
from apps.core.phone import normalize_phone


class Command(BaseCommand):
    help = (
        "Сброс TOTP платформенного аккаунта (потерян телефон): reset_totp <email|телефон>. "
        "Ключ удаляется, все выданные токены отзываются; при следующем входе владелец заново "
        "подключает аутентификатор. Команду выполняет только администратор сервера."
    )

    def add_arguments(self, parser):
        parser.add_argument("login")

    def handle(self, *args, login, **options):
        field = "email" if "@" in login else "phone"
        value = login.strip().lower() if field == "email" else normalize_phone(login)
        user = User.objects.filter(**{field: value}).first()
        if user is None or not user.is_platform_admin:
            raise CommandError("Платформенный аккаунт не найден")
        user.totp_secret, user.totp_enabled, user.totp_last_step = "", False, 0
        user.tokens_valid_after = token_clock()
        user.save(
            update_fields=["totp_secret", "totp_enabled", "totp_last_step", "tokens_valid_after"]
        )
        events.record(BillingEvent.AUTH, user.pk, "totp_reset", {}, None)
        self.stdout.write(f"{value}: TOTP сброшен, токены отозваны")
