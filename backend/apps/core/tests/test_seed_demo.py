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
