import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.billing import events
from apps.billing.models import BillingEvent
from apps.core.models import PLATFORM_OWNER, User


class Command(BaseCommand):
    help = (
        "Создать ПЕРВОГО владельца платформы (отдельный аккаунт без членства в компаниях). "
        "Пароль запрашивается интерактивно или берётся из PLATFORM_OWNER_PASSWORD. "
        "Владельцев создаёт только эта команда; публичной регистрации владельца нет."
    )

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--full-name", default="")

    def handle(self, *args, email, full_name, **options):
        import os

        email = email.strip().lower()
        if User.objects.filter(email=email).exists():
            raise CommandError("Пользователь уже существует: используйте set_platform_role")
        password = os.environ.get("PLATFORM_OWNER_PASSWORD") or getpass.getpass("Пароль: ")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from None
        user = User.objects.create_user(
            email=email, password=password, full_name=full_name, platform_role=PLATFORM_OWNER
        )
        events.record(BillingEvent.AUTH, user.pk, "owner_created", {"email": email}, None)
        self.stdout.write(f"Владелец платформы создан: {email}")
