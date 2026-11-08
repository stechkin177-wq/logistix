import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from apps.core.models import Membership, User
from apps.core.phone import normalize_phone
from apps.core.services import VALID_MODULES, create_company_with_defaults


def parse_login(raw: str) -> tuple[str, str]:
    """Логин владельца -> ('email', значение в нижнем регистре) или ('phone', +7XXXXXXXXXX)."""
    raw = (raw or "").strip()
    if "@" in raw:
        try:
            validate_email(raw)
        except ValidationError:
            raise CommandError(f"Некорректный email: {raw!r}") from None
        return "email", raw.lower()
    try:
        return "phone", normalize_phone(raw)
    except ValueError as exc:
        raise CommandError(str(exc)) from None


class Command(BaseCommand):
    help = (
        "Создаёт компанию с владельцем (роль «Администратор»). Пароль владельца берётся из "
        "переменной окружения, имя которой задано --password-env, либо запрашивается "
        "интерактивно; в аргументах командной строки и в выводе пароля нет."
    )

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Название компании")
        parser.add_argument("--owner-login", required=True, help="Email или телефон владельца")
        parser.add_argument("--owner-name", default="", help="ФИО владельца")
        parser.add_argument(
            "--modules",
            default="logistics,forwarding",
            help="Модули через запятую: logistics[,forwarding,fleet,drivers] (+ finance, docs)",
        )
        parser.add_argument(
            "--allow-existing-user",
            action="store_true",
            help="Разрешить сделать администратором компании уже существующего пользователя",
        )
        parser.add_argument(
            "--password-env", default="", help="Имя переменной окружения с паролем владельца"
        )

    def _read_password(self, password_env: str) -> str:
        if password_env:
            password = os.environ.get(password_env, "")
            if not password:
                raise CommandError(f"Переменная окружения {password_env} не задана или пуста")
            return password
        password = getpass.getpass("Пароль владельца: ")
        if password != getpass.getpass("Повторите пароль: "):
            raise CommandError("Пароли не совпадают")
        return password

    def handle(
        self,
        *args,
        name,
        owner_login,
        owner_name,
        modules,
        password_env,
        allow_existing_user,
        **options,
    ):
        name = name.strip()
        if not name:
            raise CommandError("--name не может быть пустым")
        module_list = [m.strip() for m in modules.split(",") if m.strip()]
        if not module_list or not set(module_list) <= VALID_MODULES:
            raise CommandError(f"--modules: непустое подмножество {sorted(VALID_MODULES)}")
        kind, login = parse_login(owner_login)

        owner = User.objects.filter(**{kind: login}).first()
        if owner and Membership.objects.filter(user=owner, company__name=name).exists():
            raise CommandError(
                f"Компания «{name}» с владельцем {login} уже существует - ничего не создано"
            )

        if owner is not None and not allow_existing_user:
            raise CommandError(
                f"Пользователь {login} уже существует; чтобы сделать его администратором новой "
                "компании, добавьте --allow-existing-user (пароль не меняется)"
            )
        password = None
        if owner is None:  # пароль существующего пользователя не меняется
            password = self._read_password(password_env)
            candidate = User(**{kind: login}, full_name=owner_name)
            try:
                validate_password(password, user=candidate)
            except ValidationError as exc:
                raise CommandError("Пароль не принят: " + " ".join(exc.messages)) from None

        existing = owner is not None
        with transaction.atomic():
            if owner is None:
                owner = User.objects.create_user(
                    **{kind: login}, password=password, full_name=owner_name.strip()
                )
            company = create_company_with_defaults(name, owner, module_list)

        self.stdout.write(
            self.style.SUCCESS(f"Компания создана: id={company.id}, название={company.name}")
        )
        if existing:
            self.stdout.write(
                f"существующий пользователь {login} добавлен администратором "
                "компании (пароль не менялся)"
            )
        self.stdout.write(f"Логин владельца: {login}")
