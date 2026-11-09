from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.billing import events
from apps.billing.models import BillingEvent
from apps.core import password_setup
from apps.core.models import User
from apps.core.phone import normalize_phone


class Command(BaseCommand):
    help = (
        "Одноразовая ссылка для установки нового пароля пользователем (первичная настройка или "
        "сброс забытого пароля): issue_password_link <email|телефон> --base-url https://... "
        "Пароль администратор сервера не видит и не передаёт. Старый пароль остаётся действующим, "
        "пока человек не задаст новый."
    )

    def add_arguments(self, parser):
        parser.add_argument("login")
        parser.add_argument("--base-url", required=True)

    def handle(self, *args, login, base_url, **options):
        field = "email" if "@" in login else "phone"
        value = login.strip().lower() if field == "email" else normalize_phone(login)
        user = User.objects.filter(**{field: value, "is_active": True}).first()
        if user is None:
            raise CommandError("Пользователь не найден")
        if not base_url.startswith(("https://", "http://")):
            raise CommandError("--base-url: адрес вида https://app.example.kz")
        events.record(BillingEvent.AUTH, user.pk, "password_link_issued", {}, None)
        hours = max(1, round(settings.PASSWORD_RESET_TIMEOUT / 3600))
        self.stdout.write(f"Ссылка для {value} (около {hours} ч., работает один раз):")
        self.stdout.write(password_setup.setup_url(user, base_url))
