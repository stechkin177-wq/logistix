import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import Company, Membership, User

PW_ENV = "BOOTSTRAP_TEST_PASSWORD"
STRONG = "Str0ng-owner-pass"


def run(monkeypatch, capsys, *extra, password=STRONG, name="ТОО Альфа", login="Owner@Alfa.kz"):
    if password is None:
        monkeypatch.delenv(PW_ENV, raising=False)
    else:
        monkeypatch.setenv(PW_ENV, password)
    call_command(
        "bootstrap_company",
        "--name",
        name,
        "--owner-login",
        login,
        "--owner-name",
        "Иван",
        "--password-env",
        PW_ENV,
        *extra,
    )
    return capsys.readouterr().out


@pytest.mark.django_db
def test_creates_company_and_owner(monkeypatch, capsys):
    out = run(monkeypatch, capsys, "--modules", "forwarding,fleet")
    company = Company.objects.get(name="ТОО Альфа")
    assert company.modules == ["forwarding", "fleet"]
    user = User.objects.get(email="owner@alfa.kz")
    assert user.check_password(STRONG) and user.full_name == "Иван"
    assert Membership.objects.get(user=user, company=company).role.name == "Администратор"
    assert f"id={company.id}" in out and "owner@alfa.kz" in out
    assert STRONG not in out


@pytest.mark.django_db
def test_phone_login(monkeypatch, capsys):
    run(monkeypatch, capsys, login="8 700 111 22 33")
    assert User.objects.get(phone="+77001112233")


@pytest.mark.django_db
def test_second_run_fails_without_duplicates(monkeypatch, capsys):
    run(monkeypatch, capsys)
    with pytest.raises(CommandError, match="уже существует"):
        run(monkeypatch, capsys)
    assert Company.objects.filter(name="ТОО Альфа").count() == 1
    assert User.objects.filter(email="owner@alfa.kz").count() == 1


@pytest.mark.django_db
def test_existing_user_gets_second_company_password_untouched(monkeypatch, capsys):
    run(monkeypatch, capsys)
    with pytest.raises(CommandError, match="allow-existing-user"):
        run(monkeypatch, capsys, "--modules", "forwarding", name="ТОО Бета", password=None)
    assert Company.objects.count() == 1
    out = run(monkeypatch, capsys, "--allow-existing-user", name="ТОО Бета", password=None)
    assert "существующий пользователь owner@alfa.kz добавлен администратором" in out
    assert STRONG not in out
    assert Company.objects.count() == 2
    assert User.objects.get(email="owner@alfa.kz").check_password(STRONG)


@pytest.mark.django_db
def test_weak_password_rejected(monkeypatch, capsys):
    with pytest.raises(CommandError, match="Пароль не принят"):
        run(monkeypatch, capsys, password="short")
    assert not Company.objects.filter(name="ТОО Альфа").exists()
    assert not User.objects.filter(email="owner@alfa.kz").exists()


@pytest.mark.django_db
def test_missing_password_env(monkeypatch, capsys):
    with pytest.raises(CommandError, match=PW_ENV):
        run(monkeypatch, capsys, password=None)


@pytest.mark.django_db
@pytest.mark.parametrize("modules", ["", "bogus", "forwarding,bogus"])
def test_invalid_modules(monkeypatch, capsys, modules):
    with pytest.raises(CommandError, match="modules"):
        run(monkeypatch, capsys, "--modules", modules)


@pytest.mark.django_db
@pytest.mark.parametrize("login", ["not an email@", "12345", "a@b"])
def test_invalid_login(monkeypatch, capsys, login):
    with pytest.raises(CommandError):
        run(monkeypatch, capsys, login=login)


@pytest.mark.django_db
def test_interactive_password(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": STRONG)
    call_command("bootstrap_company", "--name", "ТОО Гамма", "--owner-login", "g@gamma.kz")
    assert User.objects.get(email="g@gamma.kz").check_password(STRONG)


@pytest.mark.django_db
def test_interactive_password_mismatch(monkeypatch):
    answers = iter([STRONG, "other-Str0ng-pass"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    with pytest.raises(CommandError, match="не совпадают"):
        call_command("bootstrap_company", "--name", "X", "--owner-login", "x@x.kz")
