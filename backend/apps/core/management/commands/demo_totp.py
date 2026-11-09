import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core import totp
from apps.core.models import User


class Command(BaseCommand):
    help = (
        "Текущий код TOTP демо-владельца (только DEBUG): удобно для локального входа без телефона."
    )

    def add_arguments(self, parser):
        parser.add_argument("email", nargs="?", default="owner@demo.local")

    def handle(self, *args, email, **options):
        if not settings.DEBUG:
            raise CommandError(
                "Команда доступна только при DJANGO_DEBUG=true (локальная разработка)"
            )
        user = User.objects.filter(email=email, totp_enabled=True).first()
        if user is None or not email.endswith("@demo.local"):
            raise CommandError("Демо-аккаунт с TOTP не найден")
        now = time.time()
        step = int(now // totp.STEP_SECONDS)
        left = totp.STEP_SECONDS - int(now % totp.STEP_SECONDS)
        self.stdout.write(f"{totp.code_for(user.totp_secret, step)}  (действует ещё ~{left} с)")
