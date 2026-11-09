"""Одноразовая ссылка первоначальной установки пароля (и сброса администратором сервера).

Постоянный пароль никому не передаётся: администратор сервера создаёт аккаунт без пароля и выдаёт
ссылку, человек сам выбирает пароль. Используется токен Django (PasswordResetTokenGenerator):
привязан к хэшу пароля, поэтому после установки пароля ссылка перестаёт работать; срок -
PASSWORD_RESET_TIMEOUT (PASSWORD_SETUP_TIMEOUT_SECONDS, по умолчанию 2 часа).
"""

from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import User


def make_link_parts(user: User) -> tuple[str, str]:
    return urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)


def setup_url(user: User, base_url: str) -> str:
    uid, token = make_link_parts(user)
    return f"{base_url.rstrip('/')}/setup-password?uid={uid}&token={token}"


def user_for(uid: str, token: str) -> User | None:
    """Пользователь по ссылке, если токен действителен (не истёк и пароль не менялся)."""
    try:
        pk = int(urlsafe_base64_decode(uid).decode())
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    user = User.objects.filter(pk=pk, is_active=True).first()
    if user is None or not default_token_generator.check_token(user, token):
        return None
    return user
