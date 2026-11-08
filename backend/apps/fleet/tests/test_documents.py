"""Документы водителей и техники - через общую систему documents (единый поставщик letter)."""

import io
import zipfile
from datetime import date

import pytest

from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.drivers.models import Driver
from apps.fleet.models import Insurance, ServiceRecord, Vehicle

pytestmark = pytest.mark.django_db

ISSUED = "/api/documents/issued/"


@pytest.fixture
def co(make_company):
    return make_company("Docs", modules=["logistics", "fleet", "drivers"])


def docx_text(response):
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        return z.read("word/document.xml").decode()


def issue(api, subject_type, subject_id):
    return api.post(
        ISSUED,
        {"kind": "letter", "subject_type": subject_type, "subject_id": subject_id},
        format="json",
    )


def test_driver_vehicle_insurance_and_service_documents(co):
    company, _, api = co
    with tenant_context(company.id):
        driver = Driver.objects.create(
            full_name="Сериков Ерлан", license_number="KZ-77", license_categories="C,E"
        )
        vehicle = Vehicle.objects.create(plate="777AAA01", make="Volvo", model="FH", year=2020)
        insurance = Insurance.objects.create(
            vehicle=vehicle, kind="osago", policy_number="P-1", expires_at=date(2027, 1, 1)
        )
        service = ServiceRecord.objects.create(
            vehicle=vehicle,
            title="ТО-2",
            status="done",
            done_date=date(2026, 6, 1),
            odometer_km=120000,
            description="Замена масла и фильтров",
        )
    expected = {
        "drivers.driver": (driver.pk, ["Справка о водителе", "KZ-77"]),
        "fleet.vehicle": (vehicle.pk, ["Справка по технике", "777AAA01", "Volvo"]),
        "fleet.insurance": (insurance.pk, ["Справка о страховании", "P-1"]),
        "fleet.servicerecord": (service.pk, ["Акт об обслуживании техники", "120000", "масла"]),
    }
    for subject_type, (subject_id, parts) in expected.items():
        r = issue(api, subject_type, subject_id)
        assert r.status_code == 201, (subject_type, r.content)
        assert r.json()["subject_type"] == subject_type and r.json()["subject_id"] == subject_id
        download = api.get(f"{ISSUED}{r.json()['id']}/download/")
        assert download.status_code == 200
        text = docx_text(download)
        assert all(p in text for p in parts), (subject_type, parts)


def test_module_gating_per_subject(co):
    company, _, api = co
    with tenant_context(company.id):
        driver = Driver.objects.create(full_name="А")
        vehicle = Vehicle.objects.create(plate="A1")
    set_company_modules(company, ["logistics", "documents", "drivers"])  # fleet выключен
    assert issue(api, "fleet.vehicle", vehicle.pk).status_code in (400, 403)
    assert issue(api, "drivers.driver", driver.pk).status_code == 201
    set_company_modules(company, ["logistics", "documents", "fleet"])  # drivers выключен
    assert issue(api, "drivers.driver", driver.pk).status_code in (400, 403)
    assert issue(api, "fleet.vehicle", vehicle.pk).status_code == 201


def test_deleted_or_foreign_subject_rejected(make_company):
    a, _, api_a = make_company("A", modules=["logistics", "fleet", "drivers"])
    b, _, _ = make_company("B", modules=["logistics", "fleet", "drivers"])
    with tenant_context(b.id):
        foreign_driver = Driver.objects.create(full_name="Чужой")
        foreign_vehicle = Vehicle.objects.create(plate="F1")
    with tenant_context(a.id):
        mine = Vehicle.objects.create(plate="M1")
        ins = Insurance.objects.create(vehicle=mine, kind="osago")
    assert issue(api_a, "drivers.driver", foreign_driver.pk).status_code in (400, 404)
    assert issue(api_a, "fleet.vehicle", foreign_vehicle.pk).status_code in (400, 404)
    with tenant_context(a.id):
        mine.delete()
    assert issue(api_a, "fleet.vehicle", mine.pk).status_code in (400, 404)
    assert issue(api_a, "fleet.insurance", ins.pk).status_code in (400, 404)  # техника удалена
