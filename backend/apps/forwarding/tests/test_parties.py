import itertools
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core import trash
from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Membership, Role, User
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Carrier, Client, Contact

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-pass-91"
_n = itertools.count(1)
BIN = "123456789012"
URLS = {"clients": "/api/clients/", "carriers": "/api/carriers/"}
MODELS = {"clients": Client, "carriers": Carrier}
TYPE_CODE = {"clients": "client_type", "carriers": "carrier_type"}
RESOURCES = ["clients", "carriers"]


def client_with_role(company, role_name):
    n = next(_n)
    user = User.objects.create_user(email=f"u{n}@parties.kz", password=PASSWORD)
    with tenant_context(company.id):
        role = Role.objects.get(name=role_name)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return user, api


def type_id(company, resource, name="ИП"):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code=TYPE_CODE[resource], name=name).pk


def make(company, resource, name="Алма", **extra):
    with tenant_context(company.id):
        return MODELS[resource].objects.create(name=name, **extra)


def audit_rows(company, **filters):
    with tenant_context(company.id):
        return list(AuditLog.objects.filter(**filters).order_by("id"))


# --- создание и поля ---


@pytest.mark.parametrize("resource", RESOURCES)
def test_create_with_bin(admin_client, company, resource):
    r = admin_client.post(
        URLS[resource],
        {"name": "ТОО Алма", "bin_iin": BIN, "type": type_id(company, resource), "notes": "n"},
        format="json",
    )
    assert r.status_code == 201, r.content
    d = r.data
    assert d["bin_iin"] == BIN and d["type_name"] == "ИП" and d["status"] == "active"
    assert d["contacts"] == [] and "created_at" in d
    if resource == "clients":
        assert d["credit_limit"] == "0.00" and d["orders_count"] == 0
    else:
        assert d["rating"] is None and "orders_count" not in d
    assert admin_client.get(f"{URLS[resource]}{d['id']}/").data["name"] == "ТОО Алма"


@pytest.mark.parametrize("resource", RESOURCES)
def test_name_required_and_blank_bin_allowed(admin_client, resource):
    assert admin_client.post(URLS[resource], {"bin_iin": ""}, format="json").status_code == 400
    assert admin_client.post(URLS[resource], {"name": "  "}, format="json").status_code == 400
    r = admin_client.post(URLS[resource], {"name": "Без БИН"}, format="json")
    assert r.status_code == 201 and r.data["bin_iin"] == "" and r.data["type"] is None
    r = admin_client.post(URLS[resource], {"name": "Без БИН 2"}, format="json")
    assert r.status_code == 201  # пустые БИН не конфликтуют


@pytest.mark.parametrize("bad", ["12345", "1234567890123", "12345678901a", "١٢٣٤٥٦٧٨٩٠١٢"])
@pytest.mark.parametrize("resource", RESOURCES)
def test_bin_format_validated(admin_client, resource, bad):
    r = admin_client.post(URLS[resource], {"name": "X", "bin_iin": bad}, format="json")
    assert r.status_code == 400 and "bin_iin" in r.data


@pytest.mark.parametrize("resource", RESOURCES)
def test_ten_digit_bin_ok(admin_client, resource):
    r = admin_client.post(URLS[resource], {"name": "X", "bin_iin": "1234567890"}, format="json")
    assert r.status_code == 201


@pytest.mark.parametrize("resource", RESOURCES)
def test_duplicate_bin_is_400_with_message(admin_client, resource):
    admin_client.post(URLS[resource], {"name": "A", "bin_iin": BIN}, format="json")
    r = admin_client.post(URLS[resource], {"name": "B", "bin_iin": BIN}, format="json")
    assert r.status_code == 400
    assert "bin_iin" in r.data and "уже" in str(r.data["bin_iin"][0])
    other = admin_client.post(
        URLS[resource], {"name": "C", "bin_iin": "999999999999"}, format="json"
    )
    r = admin_client.patch(f"{URLS[resource]}{other.data['id']}/", {"bin_iin": BIN}, format="json")
    assert r.status_code == 400 and "bin_iin" in r.data


def test_same_bin_allowed_for_client_and_carrier_and_other_company(admin_client, make_company):
    assert (
        admin_client.post(URLS["clients"], {"name": "A", "bin_iin": BIN}, format="json").status_code
        == 201
    )
    assert (
        admin_client.post(
            URLS["carriers"], {"name": "A", "bin_iin": BIN}, format="json"
        ).status_code
        == 201
    )
    _, _, client_b = make_company()
    assert (
        client_b.post(URLS["clients"], {"name": "A", "bin_iin": BIN}, format="json").status_code
        == 201
    )


@pytest.mark.parametrize("resource", RESOURCES)
def test_deleted_bin_can_be_reused(admin_client, resource):
    a = admin_client.post(URLS[resource], {"name": "A", "bin_iin": BIN}, format="json")
    assert admin_client.delete(f"{URLS[resource]}{a.data['id']}/").status_code == 204
    assert (
        admin_client.post(URLS[resource], {"name": "B", "bin_iin": BIN}, format="json").status_code
        == 201
    )


def test_db_unique_constraint_backs_validation(company):
    make(company, "clients", "A", bin_iin=BIN)
    with pytest.raises(IntegrityError), transaction.atomic():
        make(company, "clients", "B", bin_iin=BIN)


def test_integrity_race_is_400_not_500(admin_client, monkeypatch):
    from apps.forwarding import api

    # валидатор пропускает дубль (гонка): отвечает БД, а не сериализатор
    monkeypatch.setattr(api.PartySerializer, "validate_bin_iin", lambda self, v: v)
    admin_client.post(URLS["clients"], {"name": "A", "bin_iin": BIN}, format="json")
    r = admin_client.post(URLS["clients"], {"name": "B", "bin_iin": BIN}, format="json")
    assert r.status_code == 400 and "bin_iin" in r.data


def test_rating_range(admin_client):
    for bad in ("5.1", "-0.1", "10", "abc"):
        r = admin_client.post(URLS["carriers"], {"name": "X", "rating": bad}, format="json")
        assert r.status_code == 400 and "rating" in r.data, bad
    for ok in ("0", "0.0", "4.5", "5.0"):
        r = admin_client.post(URLS["carriers"], {"name": "X", "rating": ok}, format="json")
        assert r.status_code == 201, ok
    r = admin_client.post(URLS["carriers"], {"name": "Y", "rating": None}, format="json")
    assert r.status_code == 201 and r.data["rating"] is None


def test_rating_db_check(company):
    with pytest.raises(IntegrityError), transaction.atomic():
        make(company, "carriers", "X", rating="5.5")


def test_credit_limit_not_negative(admin_client, company):
    r = admin_client.post(URLS["clients"], {"name": "X", "credit_limit": "-1"}, format="json")
    assert r.status_code == 400 and "credit_limit" in r.data
    r = admin_client.post(URLS["clients"], {"name": "X", "credit_limit": "1500.50"}, format="json")
    assert r.status_code == 201 and r.data["credit_limit"] == "1500.50"
    with pytest.raises(IntegrityError), transaction.atomic():
        make(company, "clients", "Y", credit_limit="-5")


def test_status_choices(admin_client):
    r = admin_client.post(URLS["clients"], {"name": "X", "status": "weird"}, format="json")
    assert r.status_code == 400 and "status" in r.data
    r = admin_client.post(URLS["clients"], {"name": "X", "status": "inactive"}, format="json")
    assert r.status_code == 201 and r.data["status"] == "inactive"


# --- тип из справочника ---


@pytest.mark.parametrize("resource", RESOURCES)
def test_type_must_be_active_value_of_right_handbook(admin_client, company, resource):
    other = "carriers" if resource == "clients" else "clients"
    wrong_handbook = type_id(company, other)
    r = admin_client.post(URLS[resource], {"name": "X", "type": wrong_handbook}, format="json")
    assert r.status_code == 400 and "type" in r.data
    tid = type_id(company, resource)
    with tenant_context(company.id):
        HandbookValue.objects.filter(pk=tid).update(is_active=False)
    r = admin_client.post(URLS[resource], {"name": "X", "type": tid}, format="json")
    assert r.status_code == 400 and "type" in r.data
    assert (
        admin_client.post(URLS[resource], {"name": "X", "type": 10**9}, format="json").status_code
        == 400
    )


def test_type_deactivated_later_keeps_existing_value_on_patch(admin_client, company):
    tid = type_id(company, "clients")
    c = admin_client.post(URLS["clients"], {"name": "X", "type": tid}, format="json")
    with tenant_context(company.id):
        HandbookValue.objects.filter(pk=tid).update(is_active=False)
    r = admin_client.patch(f"/api/clients/{c.data['id']}/", {"notes": "ok"}, format="json")
    assert r.status_code == 200 and r.data["type"] == tid
    r = admin_client.patch(f"/api/clients/{c.data['id']}/", {"type": None}, format="json")
    assert r.status_code == 200 and r.data["type"] is None


def test_used_type_value_cannot_be_deleted(admin_client, company):
    tid = type_id(company, "clients")
    admin_client.post(URLS["clients"], {"name": "X", "type": tid}, format="json")
    assert admin_client.delete(f"/api/handbook-values/{tid}/").status_code == 409


# --- контакты ---


@pytest.mark.parametrize("resource", RESOURCES)
def test_contacts_create_and_normalize(admin_client, resource):
    r = admin_client.post(
        URLS[resource],
        {
            "name": "X",
            "contacts": [
                {
                    "name": "Айгерим",
                    "position": "Менеджер",
                    "phone": "8 700 111 22 33",
                    "email": "A@Mail.KZ",
                },
                {"name": "Бауыржан", "phone": "12345"},
            ],
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    c1, c2 = r.data["contacts"]
    assert c1["phone"] == "+77001112233" and c1["email"] == "a@mail.kz" and c1["id"]
    assert c2["phone"] == "12345" and c2["email"] == "" and c2["position"] == ""
    got = admin_client.get(f"{URLS[resource]}{r.data['id']}/").data["contacts"]
    assert [c["name"] for c in got] == ["Айгерим", "Бауыржан"]


def test_contact_validation(admin_client):
    for contacts in ([{"name": ""}], [{"phone": "1"}], [{"name": "a", "email": "nope"}]):
        r = admin_client.post(URLS["clients"], {"name": "X", "contacts": contacts}, format="json")
        assert r.status_code == 400 and "contacts" in r.data, contacts


def test_contacts_replace_by_id_diff(admin_client):
    r = admin_client.post(
        URLS["clients"],
        {"name": "X", "contacts": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
        format="json",
    )
    a, b, c = r.data["contacts"]
    url = f"/api/clients/{r.data['id']}/"
    r = admin_client.patch(
        url,
        {
            "contacts": [
                {"id": a["id"], "name": "A2", "phone": "87001112233"},
                {"name": "D"},
                {"id": c["id"], "name": "C"},
            ]
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    got = {x["name"]: x for x in r.data["contacts"]}
    assert set(got) == {"A2", "C", "D"}
    assert got["A2"]["id"] == a["id"] and got["A2"]["phone"] == "+77001112233"
    assert got["C"]["id"] == c["id"] and got["D"]["id"] not in (a["id"], b["id"], c["id"])
    assert not Contact.all_objects.filter(pk=b["id"]).exists()
    # omitted -> unchanged; empty list -> all removed
    r = admin_client.patch(url, {"notes": "z"}, format="json")
    assert len(r.data["contacts"]) == 3
    r = admin_client.patch(url, {"contacts": []}, format="json")
    assert r.data["contacts"] == []
    assert admin_client.get(url).data["contacts"] == []


def test_contacts_foreign_or_other_parent_id_rejected(admin_client, make_company):
    mine = admin_client.post(
        URLS["clients"], {"name": "M", "contacts": [{"name": "m"}]}, format="json"
    )
    other = admin_client.post(
        URLS["clients"], {"name": "O", "contacts": [{"name": "o"}]}, format="json"
    )
    carrier = admin_client.post(
        URLS["carriers"], {"name": "K", "contacts": [{"name": "k"}]}, format="json"
    )
    _, _, client_b = make_company()
    theirs = client_b.post(
        URLS["clients"], {"name": "T", "contacts": [{"name": "t"}]}, format="json"
    )
    url = f"/api/clients/{mine.data['id']}/"
    for foreign in (
        other.data["contacts"][0]["id"],
        carrier.data["contacts"][0]["id"],
        theirs.data["contacts"][0]["id"],
        10**9,
    ):
        r = admin_client.patch(url, {"contacts": [{"id": foreign, "name": "steal"}]}, format="json")
        assert r.status_code == 400 and "contacts" in r.data, foreign
    assert admin_client.get(url).data["contacts"][0]["name"] == "m"
    assert admin_client.get(f"/api/clients/{other.data['id']}/").data["contacts"][0]["name"] == "o"
    assert client_b.get(f"/api/clients/{theirs.data['id']}/").data["contacts"][0]["name"] == "t"
    # id при создании и дубликаты id
    r = admin_client.post(
        URLS["clients"], {"name": "N", "contacts": [{"id": 1, "name": "x"}]}, format="json"
    )
    assert r.status_code == 400
    cid = mine.data["contacts"][0]["id"]
    r = admin_client.patch(
        url, {"contacts": [{"id": cid, "name": "a"}, {"id": cid, "name": "b"}]}, format="json"
    )
    assert r.status_code == 400


def test_contact_exactly_one_parent_db_check(company):
    cl = make(company, "clients")
    ca = make(company, "carriers")
    with tenant_context(company.id):
        for kwargs in ({}, {"client": cl, "carrier": ca}):
            with pytest.raises(IntegrityError), transaction.atomic():
                Contact.objects.create(name="x", **kwargs)
        Contact.objects.create(name="ok", client=cl)
        Contact.objects.create(name="ok", carrier=ca)


# --- список: поиск, фильтры, порядок, пагинация ---


@pytest.mark.parametrize("resource", RESOURCES)
def test_search_cyrillic_kazakh_and_bin(admin_client, company, resource):
    make(company, resource, "ТОО Алматы Транс", bin_iin="111111111111")
    make(company, resource, "Қазақстан Көлік", bin_iin="222222222222")
    make(company, resource, "Әлем Логистик")
    make(company, resource, "Другой")

    def names(q):
        r = admin_client.get(URLS[resource], {"q": q})
        assert r.status_code == 200
        return sorted(x["name"] for x in r.data["results"])

    assert names("алматы") == ["ТОО Алматы Транс"]
    assert names("АЛМАТЫ") == ["ТОО Алматы Транс"]
    assert names("қазақ") == ["Қазақстан Көлік"]
    assert names("ҚАЗАҚ") == ["Қазақстан Көлік"]
    assert names("әлем") == ["Әлем Логистик"]
    assert names("ӘЛЕМ") == ["Әлем Логистик"]
    assert names("2222") == ["Қазақстан Көлік"]
    assert names("нет такого") == []
    assert len(names("")) == 4


def test_search_escapes_like_wildcards(admin_client, company):
    make(company, "clients", "100% груз")
    make(company, "clients", "Обычный")
    r = admin_client.get("/api/clients/", {"q": "%"})
    assert [x["name"] for x in r.data["results"]] == ["100% груз"]


@pytest.mark.parametrize("resource", RESOURCES)
def test_filters_and_ordering(admin_client, company, resource):
    t_ip, t_ul = type_id(company, resource, "ИП"), type_id(company, resource, "Юридическое лицо")
    make(company, resource, "Бета", type_id=t_ip)
    make(company, resource, "Альфа", type_id=t_ul, status="inactive")
    make(company, resource, "Гамма", type_id=t_ul)
    url = URLS[resource]

    def names(**params):
        r = admin_client.get(url, params)
        assert r.status_code == 200, r.content
        return [x["name"] for x in r.data["results"]]

    assert names() == ["Альфа", "Бета", "Гамма"]  # по умолчанию name
    assert names(ordering="-name") == ["Гамма", "Бета", "Альфа"]
    assert names(type=t_ul) == ["Альфа", "Гамма"]
    assert names(status="inactive") == ["Альфа"]
    assert names(type=t_ul, status="active") == ["Гамма"]
    assert names(ordering="created_at") == ["Бета", "Альфа", "Гамма"]
    assert names(ordering="-created_at") == ["Гамма", "Альфа", "Бета"]
    assert admin_client.get(url, {"ordering": "bin_iin"}).status_code == 400
    assert admin_client.get(url, {"type": "abc"}).status_code == 400
    assert admin_client.get(url, {"status": "zzz"}).status_code == 400


def test_carrier_ordering_by_rating(admin_client, company):
    make(company, "carriers", "A", rating="3.0")
    make(company, "carriers", "B", rating="5.0")
    make(company, "carriers", "C", rating="1.5")
    make(company, "carriers", "D")
    r = admin_client.get("/api/carriers/", {"ordering": "rating"})
    assert [x["name"] for x in r.data["results"]] == ["C", "A", "B", "D"]
    r = admin_client.get("/api/carriers/", {"ordering": "-rating"})
    assert [x["name"] for x in r.data["results"]][:3] == ["B", "A", "C"]
    assert admin_client.get("/api/clients/", {"ordering": "rating"}).status_code == 400


def test_pagination(admin_client, company):
    for i in range(5):
        make(company, "clients", f"C{i}")
    r = admin_client.get("/api/clients/", {"page_size": 2})
    assert r.data["count"] == 5 and len(r.data["results"]) == 2 and r.data["next"]


@pytest.mark.parametrize("resource", RESOURCES)
def test_list_query_count_is_flat(admin_client, company, resource, django_assert_max_num_queries):
    tid = type_id(company, resource)
    for i in range(25):
        obj = make(company, resource, f"N{i:02d}", type_id=tid)
        with tenant_context(company.id):
            for j in range(2):
                Contact.objects.create(name=f"c{j}", **{resource[:-1]: obj})
    with django_assert_max_num_queries(25):
        r = admin_client.get(URLS[resource], {"q": "N", "ordering": "-name"})
    assert r.status_code == 200 and len(r.data["results"]) == 25
    assert all(len(x["contacts"]) == 2 and x["type_name"] == "ИП" for x in r.data["results"])


# --- мягкое удаление и корзина ---


@pytest.mark.parametrize("resource", RESOURCES)
def test_delete_is_soft_and_goes_to_trash(admin_client, company, resource):
    obj = make(company, resource, "Удаляемый", bin_iin=BIN)
    r = admin_client.delete(f"{URLS[resource]}{obj.pk}/")
    assert r.status_code == 204
    assert admin_client.get(f"{URLS[resource]}{obj.pk}/").status_code == 404
    assert admin_client.get(URLS[resource]).data["count"] == 0
    with tenant_context(company.id):
        assert MODELS[resource].trash.filter(pk=obj.pk).exists()
    t = admin_client.get("/api/trash/")
    assert {"code": resource, "id": obj.pk} == {k: t.data["results"][0][k] for k in ("code", "id")}
    assert t.data["results"][0]["label"] == "Удаляемый"
    r = admin_client.post(f"/api/trash/{resource}/{obj.pk}/restore/")
    assert r.status_code == 200
    assert admin_client.get(f"{URLS[resource]}{obj.pk}/").status_code == 200


def test_trash_registered():
    reg = trash.registered()
    assert reg["clients"] == (Client, "clients.view")
    assert reg["carriers"] == (Carrier, "carriers.view")


def test_trash_hidden_without_view_permission(admin_client, company):
    obj = make(company, "clients", "Скрытый")
    admin_client.delete(f"/api/clients/{obj.pk}/")
    with tenant_context(company.id):
        role = Role.objects.create(
            name="Только корзина", permissions=["trash.view", "trash.update"]
        )
    user = User.objects.create_user(email="trashonly@x.kz", password=PASSWORD)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert api.get("/api/trash/").data["results"] == []
    assert api.post(f"/api/trash/clients/{obj.pk}/restore/").status_code == 403
    assert len(admin_client.get("/api/trash/").data["results"]) == 1


@pytest.mark.parametrize("resource", RESOURCES)
def test_restore_conflicts_with_active_same_bin_is_409(admin_client, company, resource):
    old = make(company, resource, "Старый", bin_iin=BIN)
    admin_client.delete(f"{URLS[resource]}{old.pk}/")
    make(company, resource, "Новый", bin_iin=BIN)
    r = admin_client.post(f"/api/trash/{resource}/{old.pk}/restore/")
    assert r.status_code == 409
    with tenant_context(company.id):
        assert MODELS[resource].trash.filter(pk=old.pk).exists()


def test_contacts_survive_soft_delete_and_restore(admin_client, company):
    r = admin_client.post(
        URLS["clients"], {"name": "X", "contacts": [{"name": "c"}]}, format="json"
    )
    admin_client.delete(f"/api/clients/{r.data['id']}/")
    admin_client.post(f"/api/trash/clients/{r.data['id']}/restore/")
    assert admin_client.get(f"/api/clients/{r.data['id']}/").data["contacts"][0]["name"] == "c"


# --- аудит ---


@pytest.mark.parametrize("resource", RESOURCES)
def test_audit_masks_bin_and_notes_and_never_leaks(admin_client, company, resource):
    ctype = MODELS[resource]._meta.label_lower
    r = admin_client.post(
        URLS[resource],
        {
            "name": "Секрет",
            "bin_iin": BIN,
            "notes": "паспорт 123",
            "contacts": [{"name": "Лид", "phone": "87001112233", "email": "leak@mail.kz"}],
        },
        format="json",
    )
    url = f"{URLS[resource]}{r.data['id']}/"
    admin_client.patch(
        url, {"name": "Секрет2", "bin_iin": "999999999999", "notes": "другое"}, format="json"
    )
    admin_client.patch(
        url, {"contacts": [{"name": "Новый", "phone": "87009998877"}]}, format="json"
    )
    admin_client.delete(url)
    rows = audit_rows(company, object_type=ctype)
    assert [x.action for x in rows] == ["create", "update", "update", "delete"]
    create, upd, upd_contacts, delete = rows
    assert create.changes["name"] == [None, "Секрет"]
    assert create.changes["bin_iin"] == "***" and create.changes["notes"] == "***"
    assert create.changes["contacts"] == "changed"
    assert upd.changes["name"] == ["Секрет", "Секрет2"]
    assert upd.changes["bin_iin"] == "***" and upd.changes["notes"] == "***"
    assert "contacts" not in upd.changes
    assert upd_contacts.changes == {"contacts": "changed"}
    assert delete.changes["name"] == ["Секрет2", None]
    blob = " ".join(str(x.changes) for x in audit_rows(company))
    for secret in (
        BIN,
        "999999999999",
        "паспорт",
        "другое",
        "87001112233",
        "+77001112233",
        "leak@mail.kz",
        "9998877",
    ):
        assert secret not in blob
    assert all(secret not in x.object_repr for x in rows for secret in (BIN, "999999999999"))


def test_audit_unchanged_masked_and_contacts_write_nothing(admin_client, company):
    r = admin_client.post(
        URLS["clients"], {"name": "A", "bin_iin": BIN, "contacts": [{"name": "c"}]}, format="json"
    )
    url = f"/api/clients/{r.data['id']}/"
    cid = r.data["contacts"][0]["id"]
    admin_client.patch(url, {"bin_iin": BIN, "contacts": [{"id": cid, "name": "c"}]}, format="json")
    assert len(audit_rows(company, object_type="forwarding.client")) == 1


def test_audit_masked_fields_unit():
    from apps.core.audit import services

    before = {"name": "a", "bin_iin": "1"}
    after = {"name": "b", "bin_iin": "2", "notes": ""}
    assert services.diff(before, after, masked=("bin_iin", "notes")) == {
        "bin_iin": "***",
        "name": ["a", "b"],
    }
    assert services.diff(before, before, masked=("bin_iin",)) == {}
    assert services.diff(before, after) == services.diff(before, after, masked=())


# --- изоляция компаний ---


@pytest.fixture
def two(make_company):
    a = make_company("Co A")
    b = make_company("Co B")
    return a, b


@pytest.mark.parametrize("resource", RESOURCES)
def test_isolation_between_companies(two, resource):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    obj = make(comp_a, resource, "Клиент А", bin_iin=BIN)
    with tenant_context(comp_a.id):
        Contact.objects.create(name="secret-contact", **{resource[:-1]: obj})
    url = f"{URLS[resource]}{obj.pk}/"
    assert api_a.get(url).status_code == 200
    assert api_b.get(url).status_code == 404
    assert api_b.patch(url, {"name": "hack"}, format="json").status_code == 404
    assert api_b.put(url, {"name": "hack"}, format="json").status_code == 404
    assert api_b.delete(url).status_code == 404
    assert api_b.get(URLS[resource]).data["count"] == 0
    for q in ("Клиент", BIN[:5]):
        assert api_b.get(URLS[resource], {"q": q}).data["count"] == 0
    assert api_b.get(URLS[resource], {"type": type_id(comp_a, resource)}).data["count"] == 0
    assert api_a.get(url).data["name"] == "Клиент А"
    assert "secret-contact" not in api_b.get(URLS[resource]).content.decode()
    # корзина и восстановление
    api_a.delete(url)
    assert api_b.get("/api/trash/").data["results"] == []
    assert api_b.post(f"/api/trash/{resource}/{obj.pk}/restore/").status_code == 404
    with tenant_context(comp_a.id):
        assert MODELS[resource].trash.filter(pk=obj.pk).exists()
    # тот же БИН в B не конфликтует с A
    assert (
        api_b.post(URLS[resource], {"name": "B", "bin_iin": BIN}, format="json").status_code == 201
    )


@pytest.mark.parametrize("resource", RESOURCES)
def test_foreign_type_id_rejected(two, resource):
    (comp_a, _, _), (_, _, api_b) = two
    foreign = type_id(comp_a, resource)
    r = api_b.post(URLS[resource], {"name": "X", "type": foreign}, format="json")
    assert r.status_code == 400 and "type" in r.data
    mine = api_b.post(URLS[resource], {"name": "X"}, format="json")
    r = api_b.patch(f"{URLS[resource]}{mine.data['id']}/", {"type": foreign}, format="json")
    assert r.status_code == 400 and "type" in r.data


# --- права, модуль, подписка ---


@pytest.mark.parametrize("resource", RESOURCES)
def test_manager_cannot_delete(company, admin_client, resource):
    _, api = client_with_role(company, "Менеджер")
    r = api.post(URLS[resource], {"name": "M"}, format="json")
    assert r.status_code == 201
    url = f"{URLS[resource]}{r.data['id']}/"
    assert api.get(url).status_code == 200
    assert api.patch(url, {"name": "M2"}, format="json").status_code == 200
    assert api.delete(url).status_code == 403
    assert admin_client.get(url).status_code == 200


@pytest.mark.parametrize("resource", RESOURCES)
def test_observer_read_only(company, resource):
    obj = make(company, resource)
    _, api = client_with_role(company, "Наблюдатель")
    url = f"{URLS[resource]}{obj.pk}/"
    assert api.get(URLS[resource]).status_code == 200 and api.get(url).status_code == 200
    assert api.post(URLS[resource], {"name": "x"}, format="json").status_code == 403
    assert api.patch(url, {"name": "x"}, format="json").status_code == 403
    assert api.delete(url).status_code == 403


def test_role_without_section_gets_403(company):
    _, api = client_with_role(company, "Механик")
    assert api.get("/api/clients/").status_code == 403
    assert api.get("/api/carriers/").status_code == 403


def test_unauthenticated_is_401():
    assert APIClient().get("/api/clients/").status_code in (401, 403)


@pytest.mark.parametrize("resource", RESOURCES)
def test_module_disabled(make_company, resource):
    _, _, api = make_company("Fleet only", modules=["fleet"])
    r = api.get(URLS[resource])
    assert r.status_code == 403 and r.data["code"] == "module_disabled"
    assert api.post(URLS[resource], {"name": "x"}, format="json").status_code == 403


def test_readonly_subscription_blocks_writes_but_not_reads(company, admin_client):
    obj = make(company, "clients")
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get("/api/clients/").status_code == 200
    r = admin_client.post("/api/clients/", {"name": "x"}, format="json")
    assert r.status_code == 403 and r.data["code"] == "subscription_readonly"
    assert (
        admin_client.patch(f"/api/clients/{obj.pk}/", {"name": "y"}, format="json").status_code
        == 403
    )


def test_blocked_subscription_blocks_reads(company, admin_client):
    Subscription.objects.filter(company=company).update(status=Subscription.BLOCKED)
    r = admin_client.get("/api/clients/")
    assert r.status_code == 403 and r.data["code"] == "subscription_blocked"


# --- под ролью приложения (RLS включён) ---


def test_party_flows_work_under_app_role(db, api_client):
    from apps.core.services import create_company_with_defaults
    from apps.core.tests.test_rls import app_role, raw
    from conftest import TEST_PASSWORD

    with app_role():
        admin = User.objects.create_user(email="rls-party@x.kz", password=TEST_PASSWORD)
        create_company_with_defaults("RLS Party", admin, ["forwarding"])
        other = User.objects.create_user(email="rls-party2@x.kz", password=TEST_PASSWORD)
        create_company_with_defaults("RLS Party 2", other, ["forwarding"])
        resp = api_client.post(
            "/api/auth/login/", {"login": "rls-party@x.kz", "password": TEST_PASSWORD}
        )
        assert resp.status_code == 200, resp.content
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

        created = api_client.post(
            "/api/clients/",
            {
                "name": "ТОО Тест",
                "bin_iin": BIN,
                "contacts": [{"name": "К", "phone": "87001112233"}],
            },
            format="json",
        )
        assert created.status_code == 201, created.content
        cid = created.data["id"]
        carrier = api_client.post(
            "/api/carriers/", {"name": "Перевозчик", "rating": "4.5"}, format="json"
        )
        assert carrier.status_code == 201, carrier.content
        listing = api_client.get("/api/clients/", {"q": "тест"})
        assert listing.status_code == 200 and listing.data["count"] == 1
        upd = api_client.patch(
            f"/api/clients/{cid}/", {"notes": "x", "contacts": [{"name": "Н"}]}, format="json"
        )
        assert upd.status_code == 200, upd.content
        assert api_client.delete(f"/api/clients/{cid}/").status_code == 204
        assert api_client.get("/api/trash/").data["count"] == 1
        restored = api_client.post(f"/api/trash/clients/{cid}/restore/")
        assert restored.status_code == 200, restored.content
        assert api_client.get(f"/api/clients/{cid}/").data["contacts"][0]["name"] == "Н"
        assert api_client.get("/api/audit/").status_code == 200
        # без контекста компании роль приложения не видит ни строки
        assert raw("SELECT count(*) FROM forwarding_client")[0][0] == 0
        assert raw("SELECT count(*) FROM forwarding_contact")[0][0] == 0
