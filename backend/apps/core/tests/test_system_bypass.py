"""Обходы защиты системных значений через ORM напрямую и защита is_initial (fix round 1)."""

import pytest
from django.db import connection, transaction
from django.db.models import Case, Value, When

from apps.core.handbooks.models import Handbook, HandbookValue
from apps.core.handbooks.services import make_initial
from apps.core.handbooks.system_codes import (
    SystemValueProtected,
    system_code_assignment,
    system_values_maintenance,
)
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

URL = "/api/handbook-values/"
BAD = (SystemValueProtected,)


def rows(company):
    return list(HandbookValue.all_objects.filter(company=company).order_by("pk").values())


def get(company, handbook, **kw):
    with tenant_context(company.id):
        return HandbookValue.objects.select_related("handbook").get(handbook__code=handbook, **kw)


@pytest.fixture
def done(company):
    return get(company, "order_status", code="completed")


@pytest.fixture
def planned(company):
    return get(company, "trip_status", code="PLANNED")


@pytest.fixture
def free(company):
    """Несистемное значение order_status."""
    return get(company, "order_status", name="В работе")


def attempt(company, action, exc=BAD):
    """Выполняет action в контексте компании; ожидает отказ; данные в БД не меняются."""
    before = rows(company)
    with tenant_context(company.id), pytest.raises(exc), transaction.atomic():
        action()
    assert rows(company) == before


# --- QuerySet.update ---


@pytest.mark.parametrize(
    "kwargs",
    [
        {"code": "zzz"},
        {"code": ""},
        {"is_active": False},
        {"is_final": False},
    ],
)
@pytest.mark.parametrize("manager", ["objects", "all_objects"])
def test_update_of_system_row_forbidden_on_both_managers(company, done, kwargs, manager):
    attempt(company, lambda: getattr(HandbookValue, manager).filter(pk=done.pk).update(**kwargs))


def test_update_false_to_true_initial_of_system_value_forbidden(company, done):
    with connection.cursor() as cur:  # начальное место свободно, иначе сработает ограничение БД
        cur.execute(
            "UPDATE core_handbookvalue SET is_initial=false WHERE company_id=%s AND handbook_id=%s",
            [company.id, done.handbook_id],
        )
    attempt(company, lambda: HandbookValue.objects.filter(pk=done.pk).update(is_initial=True))
    attempt(
        company,
        lambda: HandbookValue.all_objects.filter(pk=done.pk).update(is_initial=Value(True)),
    )


def test_update_is_initial_of_system_initial_forbidden(company, planned):
    assert planned.is_initial
    attempt(company, lambda: HandbookValue.objects.filter(pk=planned.pk).update(is_initial=False))


def test_update_moving_system_row_to_other_handbook_forbidden(company, done):
    other = Handbook.all_objects.get(company=company, code="packaging")
    attempt(company, lambda: HandbookValue.all_objects.filter(pk=done.pk).update(handbook=other))
    attempt(
        company, lambda: HandbookValue.all_objects.filter(pk=done.pk).update(handbook_id=other.pk)
    )


def test_update_with_expression_cannot_assign_reserved_code(company, free):
    """Case/When вместо константы: проверка идёт по результату в БД, а не по аргументу."""
    # системного значения cancelled в БД нет - код свободен, но зарезервирован
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM core_handbookvalue WHERE company_id=%s AND code='cancelled' "
            "AND handbook_id=%s",
            [company.id, free.handbook_id],
        )
    expr = Case(When(pk=free.pk, then=Value("cancelled")), default=Value(""))
    attempt(company, lambda: HandbookValue.objects.filter(pk=free.pk).update(code=expr))


def test_update_allowed_fields_and_nonsystem_rows(company, done, free):
    with tenant_context(company.id):
        assert HandbookValue.objects.filter(pk=done.pk).update(name="Готов", order=70) == 1
        assert HandbookValue.objects.filter(pk=free.pk).update(
            code="mine", is_active=False, is_final=True
        )
    assert HandbookValue.all_objects.get(pk=done.pk).name == "Готов"


# --- bulk_update ---


@pytest.mark.parametrize("field,value", [("code", "x"), ("is_active", False), ("is_final", False)])
def test_bulk_update_of_system_row_forbidden(company, done, field, value):
    def run():
        obj = HandbookValue.objects.get(pk=done.pk)
        setattr(obj, field, value)
        HandbookValue.objects.bulk_update([obj], [field])

    attempt(company, run)


def test_bulk_update_is_initial_and_handbook_forbidden(company, planned):
    other = Handbook.all_objects.get(company=company, code="packaging")

    def flip():
        obj = HandbookValue.objects.get(pk=planned.pk)
        obj.is_initial = False
        HandbookValue.all_objects.bulk_update([obj], ["is_initial"])

    def move():
        obj = HandbookValue.objects.get(pk=planned.pk)
        obj.handbook = other
        HandbookValue.all_objects.bulk_update([obj], ["handbook"])

    attempt(company, flip)
    attempt(company, move)


def test_bulk_update_mixed_batch_is_atomic_and_reserved_code_forbidden(company, done, free):
    def run():
        a, b = HandbookValue.objects.get(pk=free.pk), HandbookValue.objects.get(pk=done.pk)
        a.is_active = False  # допустимо само по себе, но пакет целиком откатывается
        b.is_active = False
        HandbookValue.objects.bulk_update([a, b], ["is_active"])

    attempt(company, run)
    with connection.cursor() as cur:
        cur.execute("UPDATE core_handbookvalue SET code='' WHERE id=%s", [done.pk])  # код свободен

    def reserve():
        obj = HandbookValue.objects.get(pk=free.pk)
        obj.code = "completed"
        HandbookValue.objects.bulk_update([obj], ["code"])

    attempt(company, reserve)


def test_bulk_update_name_and_order_allowed(company, done, free):
    with tenant_context(company.id):
        a, b = HandbookValue.objects.get(pk=done.pk), HandbookValue.objects.get(pk=free.pk)
        a.name, b.order = "Выполнен", 91
        HandbookValue.objects.bulk_update([a, b], ["name", "order"])
    assert HandbookValue.all_objects.get(pk=done.pk).name == "Выполнен"


# --- bulk_create / upsert / get_or_create ---


def test_bulk_create_with_reserved_code_forbidden(company, done):
    hb = Handbook.all_objects.get(company=company, code="order_status")
    obj = HandbookValue(company=company, handbook=hb, name="Дубль", code="completed", order=80)
    attempt(company, lambda: HandbookValue.all_objects.bulk_create([obj]))
    attempt(company, lambda: HandbookValue.objects.bulk_create([obj]))


def test_bulk_create_upsert_forbidden(company, done):
    hb = Handbook.all_objects.get(company=company, code="order_status")
    obj = HandbookValue(
        pk=done.pk, company=company, handbook=hb, name="Подмена", code="completed", order=1
    )
    attempt(
        company,
        lambda: HandbookValue.all_objects.bulk_create(
            [obj],
            update_conflicts=True,
            update_fields=["name", "is_final", "is_active"],
            unique_fields=["id"],
        ),
    )
    plain = HandbookValue(pk=done.pk, company=company, handbook=hb, name="x", order=1)
    attempt(
        company,
        lambda: HandbookValue.all_objects.bulk_create(
            [plain], update_conflicts=True, update_fields=["code"], unique_fields=["id"]
        ),
    )


def test_bulk_create_regular_and_assignment_context(company):
    hb = Handbook.all_objects.get(company=company, code="packaging")
    with tenant_context(company.id):
        HandbookValue.objects.bulk_create(
            [HandbookValue(company=company, handbook=hb, name="Новая", order=99)]
        )
    hb2 = Handbook.all_objects.get(company=company, code="order_status")
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM core_handbookvalue WHERE company_id=%s AND code='cancelled'", [company.id]
        )
    with tenant_context(company.id), system_code_assignment():
        HandbookValue.objects.bulk_create(
            [HandbookValue(company=company, handbook=hb2, name="Отмена", code="cancelled", order=9)]
        )
    assert HandbookValue.all_objects.filter(company=company, code="cancelled").exists()


def test_get_or_create_and_update_or_create(company, done, free):
    hb = Handbook.all_objects.get(company=company, code="order_status")
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM core_handbookvalue WHERE company_id=%s AND code='cancelled'", [company.id]
        )
    attempt(
        company,
        lambda: HandbookValue.objects.get_or_create(
            handbook=hb, name="Фальшивая отмена", defaults={"code": "cancelled", "order": 9}
        ),
    )
    attempt(
        company,
        lambda: HandbookValue.objects.update_or_create(pk=done.pk, defaults={"is_active": False}),
    )
    attempt(
        company,
        lambda: HandbookValue.objects.update_or_create(pk=free.pk, defaults={"code": "cancelled"}),
    )
    with tenant_context(company.id):
        obj, created = HandbookValue.objects.update_or_create(pk=free.pk, defaults={"order": 55})
    assert not created and obj.order == 55


# --- delete ---


def test_deletes_through_every_path_forbidden(company, done):
    hb = Handbook.all_objects.get(company=company, code="order_status")
    attempt(company, lambda: HandbookValue.objects.all().delete())
    attempt(company, lambda: HandbookValue.all_objects.filter(pk=done.pk).delete())
    attempt(company, lambda: hb.values.all().delete())
    attempt(company, lambda: HandbookValue._default_manager.filter(pk=done.pk).delete())
    attempt(company, lambda: HandbookValue.objects.get(pk=done.pk).delete())


def test_stale_instance_cannot_bypass_guard(company, done):
    """Объект в памяти «несистемный», а в БД строка системная: решает строка БД."""
    with tenant_context(company.id):
        stale = HandbookValue.objects.get(pk=done.pk)
    stale.code, stale.is_final, stale.is_active = "", False, False
    attempt(company, stale.delete)
    attempt(company, stale.save)
    attempt(company, lambda: stale.save(update_fields=["code"]))
    attempt(company, lambda: stale.save(update_fields=["is_final", "is_active"]))


def test_save_update_fields_and_handbook_move_forbidden(company, done, planned):
    other = Handbook.all_objects.get(company=company, code="packaging")
    with tenant_context(company.id):
        d = HandbookValue.objects.get(pk=done.pk)
        p = HandbookValue.objects.get(pk=planned.pk)
    d.is_final = False
    attempt(company, lambda: d.save(update_fields=["is_final"]))
    d.is_final = True
    d.handbook = other
    attempt(company, d.save)
    attempt(company, lambda: d.save(update_fields=["handbook"]))
    p.is_initial = False
    attempt(company, lambda: p.save(update_fields=["is_initial"]))
    attempt(company, p.save)


def test_save_with_existing_pk_as_new_object_cannot_overwrite(company, done):
    hb = Handbook.all_objects.get(company=company, code="order_status")
    fake = HandbookValue(
        pk=done.pk, company=company, handbook=hb, name="Подмена", code="other", order=1
    )
    attempt(company, fake.save)


def test_unrelated_update_fields_save_is_allowed(company, done):
    with tenant_context(company.id):
        obj = HandbookValue.objects.get(pk=done.pk)
        obj.name = "Закрыт"
        obj.save(update_fields=["name"])
    assert HandbookValue.all_objects.get(pk=done.pk).name == "Закрыт"


# --- внутренний обход (служебное удаление компании, очистка) ---


def test_maintenance_context_is_the_only_bypass(company, done):
    with tenant_context(company.id):
        with system_values_maintenance():
            HandbookValue.objects.filter(pk=done.pk).update(is_final=False)
            HandbookValue.objects.get(pk=done.pk).delete()
        assert not HandbookValue.objects.filter(pk=done.pk).exists()
        # после выхода из контекста защита снова действует
        other = HandbookValue.objects.get(handbook__code="order_status", code="cancelled")
        with pytest.raises(SystemValueProtected):
            other.delete()


# --- is_initial ---


def test_api_cannot_change_initial_flag_of_system_value(admin_client, company, planned):
    for body in ({"is_initial": False},):
        r = admin_client.patch(f"{URL}{planned.pk}/", body, format="json")
        assert r.status_code == 400 and "is_initial" in r.json()
    done = get(company, "trip_status", code="COMPLETED")
    r = admin_client.patch(f"{URL}{done.pk}/", {"is_initial": True}, format="json")
    assert r.status_code == 400
    assert HandbookValue.all_objects.get(pk=planned.pk).is_initial is True


def test_api_system_initial_can_be_renamed_and_reordered(admin_client, planned):
    r = admin_client.patch(f"{URL}{planned.pk}/", {"name": "Черновик", "order": 40}, format="json")
    assert r.status_code == 200 and r.json()["is_initial"] is True and r.json()["is_system"]


def test_make_initial_blocked_while_initial_is_system(admin_client, company, planned):
    other = get(company, "trip_status", code="ASSIGNED")
    r = admin_client.post(f"{URL}{other.pk}/make-initial/")
    assert r.status_code == 400
    assert "системный" in str(r.json()) and "Планируется" in str(r.json())
    assert HandbookValue.all_objects.get(pk=planned.pk).is_initial is True
    assert not HandbookValue.all_objects.get(pk=other.pk).is_initial
    with tenant_context(company.id):
        with pytest.raises(SystemValueProtected):
            make_initial(HandbookValue.objects.select_related("handbook").get(pk=other.pk))
    assert HandbookValue.all_objects.get(pk=planned.pk).is_initial is True


def test_make_initial_still_works_for_nonsystem_initial(admin_client, company):
    """consignment_status не в реестре: перенос начального по-прежнему работает."""
    with tenant_context(company.id):
        first = HandbookValue.objects.get(handbook__code="consignment_status", is_initial=True)
        other = HandbookValue.objects.get(handbook__code="consignment_status", name="На складе")
    assert admin_client.post(f"{URL}{other.pk}/make-initial/").status_code == 200
    assert HandbookValue.all_objects.get(pk=other.pk).is_initial
    assert not HandbookValue.all_objects.get(pk=first.pk).is_initial
    # и в order_status начальный «Новый» не системный
    new = get(company, "order_status", name="В работе")
    assert admin_client.post(f"{URL}{new.pk}/make-initial/").status_code == 200
