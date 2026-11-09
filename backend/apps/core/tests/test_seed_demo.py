"""Локальная тестовая БД: seed_demo создаёт вымышленные данные и работает только локально."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import Company, Membership, User
from apps.core.tenancy import tenant_context
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.models import Order
from apps.forwarding.trips.models import Trip

pytestmark = pytest.mark.django_db


def test_seed_creates_two_companies_one_dual_account_and_scenario(settings, capsys):
    settings.DEBUG = True
    call_command("seed_demo")
    out = capsys.readouterr().out
    assert "owner@demo.local" in out and "Ключ TOTP" in out
    owner = User.objects.get(email="owner@demo.local")
    assert owner.platform_role == "owner" and owner.totp_enabled and not owner.is_superuser
    assert (
        Membership.objects.filter(user=owner).count() == 1
    )  # один аккаунт: платформа + своя компания
    a = Company.objects.get(name__contains="Демо-Перевозчик")
    b = Company.objects.get(name__contains="Демо-Экспедитор")
    with tenant_context(a.id):
        assert Order.objects.count() == 5 and Trip.objects.count() == 3
        # сценарий legacy: ставка клиента 250 000, расход перевозчику 180 000 связан с рейсом
        line = OrderService.objects.get(expense=180000)
        assert line.trip_id is not None and line.order.client_rate == 250000
    with tenant_context(b.id):
        assert Order.objects.count() == 1


def test_seed_refuses_without_debug_and_when_data_exists(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("seed_demo")
    settings.DEBUG = True
    call_command("seed_demo")
    with pytest.raises(CommandError, match="уже есть данные"):
        call_command("seed_demo")


def test_demo_totp_is_debug_only(settings, capsys):
    settings.DEBUG = True
    call_command("seed_demo")
    capsys.readouterr()
    call_command("demo_totp")
    assert len(capsys.readouterr().out.split()[0]) == 6
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("demo_totp")


def test_remote_demo_mode_needs_explicit_ref_and_has_no_preset_secrets(
    settings, monkeypatch, capsys
):
    """Демо на внешней БД: нужны ключ и ref; владелец без пароля и TOTP, прочие - случайные пароли."""
    from django.db import connection

    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEMO_SEED_ALLOW_REF"):
        call_command("seed_demo", "--remote-demo")
    monkeypatch.setenv("DEMO_SEED_ALLOW_REF", "abcref")
    monkeypatch.setenv("DEMO_BASE_URL", "https://demo.example.app")
    with pytest.raises(
        CommandError, match="DEMO_SEED_ALLOW_REF"
    ):  # пользователь подключения без .ref
        call_command("seed_demo", "--remote-demo")
    monkeypatch.setitem(
        connection.settings_dict, "USER", f"{connection.settings_dict['USER']}.abcref"
    )
    call_command("seed_demo", "--remote-demo")
    out = capsys.readouterr().out
    owner = User.objects.get(email="owner@demo.local")
    assert owner.platform_role == "owner" and not owner.has_usable_password()
    assert owner.totp_enabled is False and owner.totp_secret == ""
    assert "OWNER_LINK=https://demo.example.app/setup-password?uid=" in out
    accounts = dict(line.split()[1:3] for line in out.splitlines() if line.startswith("ACCOUNT "))
    assert set(accounts) == {"manager@demo.local", "accountant@demo.local", "admin@b.demo.local"}
    assert all(len(p) >= 16 for p in accounts.values()) and len(set(accounts.values())) == 3
    assert "Demo-pass-2026!" not in out
    for email, pw in accounts.items():
        assert User.objects.get(email=email).check_password(pw)
