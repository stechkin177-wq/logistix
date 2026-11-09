import getpass
import os

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.billing import events
from apps.billing.models import BillingEvent
from apps.core import password_setup
from apps.core.models import PLATFORM_OWNER, User


class Command(BaseCommand):
    help = (
        "Создать ПЕРВОГО владельца платформы. По умолчанию аккаунт создаётся БЕЗ пароля и команда "
        "печатает одноразовую ссылку (--base-url), по которой человек сам задаёт пароль; "
        "постоянный пароль никому не передаётся. При первом входе владелец сам подключает TOTP. "
        "Аккаунт создаётся без членства в компаниях; для работы в своей компании тот же аккаунт "
        "добавляется администратором компании командой bootstrap_company --allow-existing-user. "
        "Публичной регистрации владельца нет."
    )

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--full-name", default="")
        parser.add_argument(
            "--base-url", default=os.environ.get("LOGISTIX_BASE_URL", ""),
            help="Адрес приложения (https://...), для ссылки установки пароля",
        )  # fmt: skip
        parser.add_argument(
            "--password-env", default="",
            help="Имя переменной окружения с готовым паролем (вместо ссылки; для автоматизации)",
        )  # fmt: skip

    def handle(self, *args, email, full_name, base_url, password_env, **options):
        email = email.strip().lower()
        if User.objects.filter(email=email).exists():
            raise CommandError("Пользователь уже существует: используйте set_platform_role")
        if password_env:
            password = os.environ.get(password_env) or getpass.getpass("Пароль: ")
            try:
                validate_password(password)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from None
            user = User.objects.create_user(
                email=email, password=password, full_name=full_name, platform_role=PLATFORM_OWNER
            )
            link = None
        else:
            if not base_url.startswith(("https://", "http://")):
                raise CommandError(
                    "Укажите --base-url (или LOGISTIX_BASE_URL), например https://app.example.kz"
                )
            user = User.objects.create_user(
                email=email, password=None, full_name=full_name, platform_role=PLATFORM_OWNER
            )
            link = password_setup.setup_url(user, base_url)
        events.record(BillingEvent.AUTH, user.pk, "owner_created", {"email": email}, None)
        self.stdout.write(f"Владелец платформы создан: {email}")
        if link:
            hours = max(1, round(settings.PASSWORD_RESET_TIMEOUT / 3600))
            self.stdout.write(
                f"Одноразовая ссылка установки пароля (около {hours} ч., работает один раз; "
                "передать владельцу личным закрытым каналом):"
            )
            self.stdout.write(link)
