"""Защита системных кодов справочников: API, модель, queryset, реестр (задача 1.1, блок B)."""

import pytest
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.core.handbooks.defaults import DEFAULTS
from apps.core.handbooks.models import Handbook, HandbookValue
from apps.core.handbooks.system_codes import (
    SYSTEM_CODES,
    SystemValueProtected,
    is_system_code,
    system_code_assignment,
)
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

URL = "/api/handbook-values/"


def vid(company, handbook, code=None, name=None):
    with tenant_context(company.id):
        qs = HandbookValue.objects.filter(handbook__code=handbook)
        return qs.get(code=code).pk if code is not None else qs.get(name=name).pk


def row(pk):
    return HandbookValue.all_objects.values("code", "name", "order", "is_active", "is_final").get(
        pk=pk
    )


@pytest.fixture
def done(company):
    """Системное значение order_status.completed."""
    return vid(company, "order_status", "completed")


def test_registry_shape_is_extensible_mapping_of_frozensets():
    assert SYSTEM_CODES["order_status"] == {"completed", "cancelled"}
    assert SYSTEM_CODES["trip_status"] == {
        "PLANNED",
        "ASSIGNED",
        "IN_PROGRESS",
        "UNLOADING",
        "COMPLETED",
        "CANCELLED",
    }
    assert all(isinstance(v, frozenset) for v in SYSTEM_CODES.values())
    assert is_system_code("order_status", "completed")
    assert not is_system_code("trip_status", "completed")  # свой справочник у каждого кода
    assert not is_system_code("order_status", "")


def test_defaults_codes_match_registry():
    """Набор кодов значений по умолчанию совпадает с реестром системных кодов справочника."""
    for handbook, codes in SYSTEM_CODES.items():
        seeded = {v["code"] for v in DEFAULTS[handbook]["values"] if v.get("code")}
        assert seeded == set(codes), handbook


def test_is_system_exposed_read_only_in_api(admin_client, company, done):
    got = admin_client.get(f"{URL}{done}/").json()
    assert got["is_system"] is True
    listed = admin_client.get(URL, {"handbook": "order_status"}).json()
    assert {v["code"]: v["is_system"] for v in listed if v["code"]} == {
        "completed": True,
        "cancelled": True,
    }
    assert all(v["is_system"] is False for v in listed if not v["code"])
    detail = admin_client.get("/api/handbooks/", {"code": "order_status"}).json()
    assert {v["name"]: v["is_system"] for v in detail["values"]}["Завершён"] is True
    # поле только для чтения: попытка записи игнорируется
    other = vid(company, "packaging", name="Паллета")
    r = admin_client.patch(f"{URL}{other}/", {"is_system": True}, format="json")
    assert r.status_code == 200 and r.json()["is_system"] is False
    assert admin_client.get(URL, {"handbook": "currency"}).json()[0]["is_system"] is False


# --- запрещённое через API ---


@pytest.mark.parametrize(
    "body,field",
    [
        ({"code": "done"}, "code"),
        ({"code": ""}, "code"),
        ({"is_active": False}, "is_active"),
        ({"is_final": False}, "is_final"),
    ],
)
def test_api_forbids_changing_key_fields_of_system_value(admin_client, company, done, body, field):
    before = row(done)
    r = admin_client.patch(f"{URL}{done}/", body, format="json")
    assert r.status_code == 400 and field in r.json(), r.content
    assert row(done) == before  # данные не изменились


def test_api_forbids_put_changing_code_and_moving_handbook(admin_client, company, done):
    before = row(done)
    body = {"handbook": "order_status", "name": "Завершён", "code": "other", "is_final": True}
    assert admin_client.put(f"{URL}{done}/", body, format="json").status_code == 400
    moved = admin_client.patch(f"{URL}{done}/", {"handbook": "packaging"}, format="json")
    assert moved.status_code == 400
    assert row(done) == before


def test_api_forbids_delete_of_system_value(admin_client, company, done):
    r = admin_client.delete(f"{URL}{done}/")
    assert r.status_code == 400
    assert (
        "Системное значение" in str(r.json()) and HandbookValue.all_objects.filter(pk=done).exists()
    )


def test_api_allows_rename_order_and_unchanged_key_fields(admin_client, company, done):
    r = admin_client.patch(f"{URL}{done}/", {"name": "Выполнен", "order": 99}, format="json")
    assert r.status_code == 200 and r.json()["name"] == "Выполнен" and r.json()["order"] == 99
    # повторная отправка тех же ключевых значений (как делает форма целиком) допустима
    same = {"code": "completed", "is_final": True, "is_active": True, "name": "Готово"}
    r = admin_client.patch(f"{URL}{done}/", same, format="json")
    assert r.status_code == 200 and row(done)["name"] == "Готово"
    assert row(done)["code"] == "completed" and row(done)["is_final"] is True


def test_nonsystem_value_cannot_take_reserved_code_even_if_system_one_is_missing(
    admin_client, company, done
):
    other = vid(company, "order_status", name="В работе")
    r = admin_client.patch(f"{URL}{other}/", {"code": "cancelled"}, format="json")
    assert r.status_code == 400  # код занят системным значением
    # queryset-delete системного значения защищён и не удаляет его
    with tenant_context(company.id), pytest.raises(SystemValueProtected):
        HandbookValue.all_objects.filter(pk=done).delete()
    assert HandbookValue.all_objects.filter(pk=done).exists()


def test_reserved_code_cannot_be_given_when_system_value_is_absent(admin_client, company):
    """Системного значения нет (удалено напрямую в БД) - новому значению код всё равно не дать."""
    with tenant_context(company.id):
        gone = HandbookValue.all_objects.get(handbook__code="order_status", code="cancelled")
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_handbookvalue WHERE id=%s", [gone.pk])
    r = admin_client.post(
        URL,
        {"handbook": "order_status", "name": "Отказ", "code": "cancelled", "is_final": True},
        format="json",
    )
    assert r.status_code == 400 and "code" in r.json()
    ok = admin_client.post(URL, {"handbook": "order_status", "name": "Отказ"}, format="json")
    assert ok.status_code == 201
    free = admin_client.patch(f"{URL}{ok.json()['id']}/", {"code": "cancelled"}, format="json")
    assert free.status_code == 400


def test_same_code_in_other_handbook_is_not_reserved(admin_client, company):
    r = admin_client.post(
        URL, {"handbook": "packaging", "name": "Особая", "code": "completed"}, format="json"
    )
    assert r.status_code == 201 and r.json()["is_system"] is False


# --- уровень модели и queryset: обход API невозможен ---


def test_model_delete_of_system_value_is_forbidden(company, done):
    with tenant_context(company.id):
        value = HandbookValue.objects.select_related("handbook").get(pk=done)
        assert value.is_system
        with pytest.raises(SystemValueProtected) as ei:
            value.delete()
    assert isinstance(ei.value, ValidationError) and "Системное значение" in str(ei.value.detail)
    assert HandbookValue.all_objects.filter(pk=done).exists()


def test_queryset_delete_and_update_of_system_values_are_forbidden(company, done):
    with tenant_context(company.id):
        with pytest.raises(SystemValueProtected), transaction.atomic():
            HandbookValue.objects.filter(handbook__code="order_status").delete()
        with pytest.raises(SystemValueProtected), transaction.atomic():
            HandbookValue.all_objects.filter(pk=done).update(code="x")
        with pytest.raises(SystemValueProtected), transaction.atomic():
            HandbookValue.objects.filter(pk=done).update(is_active=False)
        with pytest.raises(SystemValueProtected), transaction.atomic():
            HandbookValue.objects.filter(pk=done).update(is_final=False)
        # неключевые поля и не системные значения - без ограничений
        assert HandbookValue.objects.filter(pk=done).update(order=50) == 1
        assert HandbookValue.objects.filter(handbook__code="packaging").update(is_active=False)
        HandbookValue.objects.filter(handbook__code="packaging", name="Бочка").delete()
    assert row(done)["code"] == "completed" and row(done)["is_final"] is True


def test_model_save_guards_key_fields(company, done):
    with tenant_context(company.id):
        value = HandbookValue.objects.select_related("handbook").get(pk=done)
        for field, new in (("code", "zzz"), ("is_active", False), ("is_final", False)):
            old = getattr(value, field)
            setattr(value, field, new)
            with pytest.raises(SystemValueProtected):
                value.save()
            setattr(value, field, old)
        value.name, value.order = "Закрыт", 77
        value.save()
        value.refresh_from_db()
        assert (value.name, value.order, value.code) == ("Закрыт", 77, "completed")


def test_model_save_blocks_reserved_code_on_nonsystem(company):
    with tenant_context(company.id):
        value = HandbookValue.objects.select_related("handbook").get(
            handbook__code="order_status", name="В работе"
        )
        value.code = "completed"
        with pytest.raises(SystemValueProtected):
            value.save()
        hb = Handbook.objects.get(code="order_status")
        with pytest.raises(SystemValueProtected):
            HandbookValue.objects.create(handbook=hb, name="Дубль", code="cancelled", order=50)
        with pytest.raises((SystemValueProtected, IntegrityError)), transaction.atomic():
            HandbookValue.objects.filter(pk=value.pk).update(code="cancelled")


def test_assignment_context_allows_giving_reserved_code(company):
    with tenant_context(company.id):
        value = HandbookValue.objects.select_related("handbook").get(
            handbook__code="order_status", name="В работе"
        )
        value.code = "cancelled"
        with pytest.raises(SystemValueProtected):
            value.save()
    # контекст не пропускает дубль кода: уникальность держит ограничение БД
    with tenant_context(company.id), system_code_assignment():
        value.code = "NEW"
        value.save()  # несистемный код - разрешено и так
    assert row(value.pk)["code"] == "NEW"


def test_unrelated_saves_do_not_query_extra(company, django_assert_num_queries):
    with tenant_context(company.id):
        value = HandbookValue.objects.select_related("handbook").get(
            handbook__code="packaging", name="Паллета"
        )
        value.name = "Поддон"
        value.save(update_fields=["name"])  # без проверки ключевых полей
        value.refresh_from_db()
    assert value.name == "Поддон"
