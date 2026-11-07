"""Системные коды статусов рейса: значения по умолчанию, миграция данных, команды (блок C)."""

import importlib
from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.core.management import CommandError, call_command
from django.db import connection

from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.handbooks.system_codes import SYSTEM_CODES
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

EXPECTED = {
    "Планируется": ("PLANNED", True, False),
    "Ожидает выезда": ("ASSIGNED", False, False),
    "В пути": ("IN_PROGRESS", False, False),
    "Выгрузка": ("UNLOADING", False, False),
    "Завершён": ("COMPLETED", False, True),
    "Отменён": ("CANCELLED", False, True),
}
migration = importlib.import_module("apps.core.migrations.0011_trip_status_codes")


def values(company):
    with tenant_context(company.id):
        return list(
            HandbookValue.objects.filter(handbook__code="trip_status").order_by("order", "id")
        )


def by_name(company, name):
    return next(v for v in values(company) if v.name == name)


def codes(company):
    return {v.name: v.code for v in values(company)}


def sql(query, params=()):
    """Прямой SQL: ORM-защита не даёт снять системный код."""
    with connection.cursor() as cur:
        cur.execute(query, params)


def strip_codes(company):
    sql(
        "UPDATE core_handbookvalue SET code='' WHERE company_id=%s AND handbook_id IN "
        "(SELECT id FROM core_handbook WHERE company_id=%s AND code='trip_status')",
        [company.id, company.id],
    )


def run_command(name, *args):
    out = StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


def snapshot(company):
    return [(v.pk, v.name, v.code, v.is_initial, v.is_final, v.is_active) for v in values(company)]


def test_new_company_gets_trip_status_codes(company):
    assert codes(company) == {name: spec[0] for name, spec in EXPECTED.items()}
    for v in values(company):
        assert (v.code, v.is_initial, v.is_final) == EXPECTED[v.name]
    assert {v.code for v in values(company)} == SYSTEM_CODES["trip_status"]
    assert len(values(company)) == 6  # «Выгрузка» не объединена с «В пути»


def test_migration_assigns_codes_to_standard_company(company):
    strip_codes(company)
    assert set(codes(company).values()) == {""}
    migration.run_backfill(django_apps)
    assert codes(company) == {name: spec[0] for name, spec in EXPECTED.items()}


def test_migration_is_idempotent_and_keeps_other_data(company):
    strip_codes(company)
    migration.run_backfill(django_apps)
    first = snapshot(company)
    migration.run_backfill(django_apps)
    assert snapshot(company) == first


def test_migration_skips_renamed_value(company):
    strip_codes(company)
    HandbookValue.all_objects.filter(pk=by_name(company, "Выгрузка").pk).update(name="Разгрузка")
    migration.run_backfill(django_apps)
    got = codes(company)
    assert got["Разгрузка"] == "" and got["В пути"] == "IN_PROGRESS" and got["Завершён"]
    assert sum(1 for c in got.values() if c) == 5


@pytest.mark.parametrize("name", ["завершён", "Завершён ", " Завершён", "ЗАВЕРШЁН"])
def test_migration_name_match_is_strict(company, name):
    strip_codes(company)
    HandbookValue.all_objects.filter(pk=by_name(company, "Завершён").pk).update(name=name)
    migration.run_backfill(django_apps)
    assert codes(company)[name] == ""


def test_migration_skips_duplicate_names(company):
    strip_codes(company)
    hb = by_name(company, "В пути").handbook_id
    HandbookValue.all_objects.create(company=company, handbook_id=hb, name="В пути", order=50)
    migration.run_backfill(django_apps)
    in_way = [v for v in values(company) if v.name == "В пути"]
    assert len(in_way) == 2 and all(v.code == "" for v in in_way)
    assert by_name(company, "Планируется").code == "PLANNED"


def test_migration_skips_mismatched_flags(company):
    strip_codes(company)
    HandbookValue.all_objects.filter(pk=by_name(company, "Завершён").pk).update(is_final=False)
    HandbookValue.all_objects.filter(pk=by_name(company, "Ожидает выезда").pk).update(is_final=True)
    migration.run_backfill(django_apps)
    got = codes(company)
    assert got["Завершён"] == "" and got["Ожидает выезда"] == ""
    assert got["Отменён"] == "CANCELLED"


def test_migration_skips_when_code_taken(company):
    strip_codes(company)
    sql(
        "UPDATE core_handbookvalue SET code='PLANNED', name='Новый черновик' WHERE id=%s",
        [by_name(company, "Ожидает выезда").pk],
    )
    migration.run_backfill(django_apps)
    got = codes(company)
    assert got["Планируется"] == "" and got["Новый черновик"] == "PLANNED"


def test_migration_does_not_override_existing_other_code(company):
    strip_codes(company)
    sql("UPDATE core_handbookvalue SET code='X1' WHERE id=%s", [by_name(company, "Отменён").pk])
    migration.run_backfill(django_apps)
    assert codes(company)["Отменён"] == "X1"


def test_migration_covers_every_company(make_company):
    (a, _, _), (b, _, _) = make_company("A"), make_company("B")
    for c in (a, b):
        strip_codes(c)
    HandbookValue.all_objects.filter(pk=by_name(b, "В пути").pk).update(name="Едет")
    migration.run_backfill(django_apps)
    assert codes(a)["В пути"] == "IN_PROGRESS" and codes(b)["Едет"] == ""
    assert codes(b)["Планируется"] == "PLANNED"


# --- check_system_status_codes ---


def test_check_command_standard_company_is_clean_and_read_only(company):
    before = snapshot(company)
    out = run_command("check_system_status_codes", "--company", str(company.id))
    assert "Все системные коды назначены" in out
    assert "PLANNED: назначен" in out and "COMPLETED: назначен" in out
    assert "completed: назначен" in out  # справочник order_status тоже в реестре
    assert snapshot(company) == before


def test_check_command_reports_renamed_duplicates_and_candidates(company):
    strip_codes(company)
    migration.run_backfill(django_apps)
    sql("UPDATE core_handbookvalue SET code='' WHERE id=%s", [by_name(company, "Выгрузка").pk])
    HandbookValue.all_objects.filter(pk=by_name(company, "Выгрузка").pk).update(name="Разгрузка")
    sql("UPDATE core_handbookvalue SET code='' WHERE id=%s", [by_name(company, "Отменён").pk])
    hb = by_name(company, "В пути").handbook_id
    HandbookValue.all_objects.create(
        company=company, handbook_id=hb, name="Отменён", order=60, is_final=True
    )
    before = snapshot(company)
    out = run_command("check_system_status_codes", "--company", str(company.id))
    assert "UNLOADING: НЕ назначен; требует ручной проверки" in out
    assert "нет значения с точным названием «Выгрузка»" in out
    assert "CANCELLED: НЕ назначен; требует ручной проверки" in out
    assert "несколько значений с названием «Отменён»: 2" in out
    assert "кандидат:" in out and "Отменён" in out
    assert "Итого кодов без значения: 2" in out
    assert snapshot(company) == before  # ничего не изменено


def test_check_command_lists_unambiguous_candidate_and_all_companies(make_company):
    (a, _, _), (b, _, _) = make_company("A"), make_company("B")
    strip_codes(b)
    out = run_command("check_system_status_codes")
    assert f"Компания #{a.id}" in out and f"Компания #{b.id}" in out
    assert "однозначное совпадение" in out


def test_check_command_unknown_company():
    with pytest.raises(CommandError):
        run_command("check_system_status_codes", "--company", "999999")


# --- assign_system_status_code ---


def assign(company, value, code, *extra):
    return run_command(
        "assign_system_status_code",
        "--company",
        str(company.id),
        "--value",
        str(value.pk),
        "--code",
        code,
        *extra,
    )


@pytest.fixture
def renamed(company):
    """Компания, где «Выгрузка» переименована и без кода."""
    sql("UPDATE core_handbookvalue SET code='' WHERE id=%s", [by_name(company, "Выгрузка").pk])
    value = by_name(company, "Выгрузка")
    HandbookValue.all_objects.filter(pk=value.pk).update(name="Разгрузка")
    return by_name(company, "Разгрузка")


def test_assign_sets_code_and_writes_audit(company, renamed):
    out = assign(company, renamed, "UNLOADING")
    assert "назначен код UNLOADING" in out
    assert by_name(company, "Разгрузка").code == "UNLOADING"
    with tenant_context(company.id):
        row = AuditLog.objects.filter(
            object_type="core.handbookvalue", object_id=str(renamed.pk)
        ).get()
    assert row.action == "update" and row.changes["code"] == ["", "UNLOADING"]
    # теперь значение системное: защита действует
    with tenant_context(company.id):
        from apps.core.handbooks.system_codes import SystemValueProtected

        value = HandbookValue.objects.select_related("handbook").get(pk=renamed.pk)
        assert value.is_system
        with pytest.raises(SystemValueProtected):
            value.delete()


def test_assign_is_idempotent(company, renamed):
    assign(company, renamed, "UNLOADING")
    with tenant_context(company.id):
        count = AuditLog.objects.filter(object_id=str(renamed.pk)).count()
    out = assign(company, renamed, "UNLOADING")
    assert "уже имеет код" in out
    with tenant_context(company.id):
        assert AuditLog.objects.filter(object_id=str(renamed.pk)).count() == count


def test_assign_dry_run_writes_nothing(company, renamed):
    before = snapshot(company)
    audits = AuditLog.all_objects.count()
    out = assign(company, renamed, "UNLOADING", "--dry-run")
    assert "[dry-run]" in out and "UNLOADING" in out
    assert snapshot(company) == before and AuditLog.all_objects.count() == audits


def test_assign_rejects_invalid_requests(company, make_company, renamed):
    other_company = make_company("Other")[0]
    with pytest.raises(CommandError, match="не входит в реестр"):
        assign(company, renamed, "FOO")
    with pytest.raises(CommandError, match="не входит в реестр"):
        assign(company, renamed, "completed")  # код другого справочника
    with pytest.raises(CommandError, match="уже занят"):
        assign(company, renamed, "COMPLETED")
    coded = by_name(company, "Завершён")
    with pytest.raises(CommandError, match="уже есть код"):
        assign(company, coded, "UNLOADING")
    with tenant_context(company.id):
        order_value = HandbookValue.objects.get(handbook__code="packaging", name="Паллета")
    with pytest.raises(CommandError, match="не из справочника trip_status"):
        assign(company, order_value, "UNLOADING")
    with pytest.raises(CommandError, match="не найдено"):
        assign(other_company, renamed, "UNLOADING")  # чужая компания
    with pytest.raises(CommandError, match="не найдена"):
        run_command(
            "assign_system_status_code", "--company", "999999", "--value", "1", "--code", "PLANNED"
        )
    assert by_name(company, "Разгрузка").code == ""


def test_assign_warns_on_unusual_flags_but_assigns(company, renamed):
    HandbookValue.all_objects.filter(pk=renamed.pk).update(is_final=True)
    out = assign(company, renamed, "UNLOADING")
    assert "Внимание" in out and by_name(company, "Разгрузка").code == "UNLOADING"
