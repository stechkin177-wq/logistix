"""A4: правила включения и отключения модулей (тариф, зависимости, защита finance)."""

from datetime import date

import pytest

from apps.billing.models import Plan
from apps.core.handbooks.models import HandbookValue
from apps.core.models import CompanyModule
from apps.core.module_services import (
    ModuleConfigError,
    describe_modules,
    disable_module,
    enable_module,
    enabled_module_codes,
)
from apps.core.tenancy import tenant_context
from apps.finance.models import CompanyFinancialSettings

pytestmark = pytest.mark.django_db

ALL_PLAN = [
    "logistics", "forwarding", "fleet", "finance", "documents", "drivers", "driver_app", "gps",
    "ocr",
    "notifications", "analytics",
]  # fmt: skip


@pytest.fixture
def wide_plan(db):
    """Тариф start со всеми модулями каталога (иначе планируемые модули недоступны по тарифу)."""
    Plan.objects.filter(code="start").update(modules=ALL_PLAN)


def code_of(exc_info):
    return exc_info.value.detail["code"]


def state(company):
    company.refresh_from_db()
    codes = enabled_module_codes(company.id)
    assert company.modules == codes  # проекция = CompanyModule
    return set(codes)


def test_enable_requires_catalog_non_core_and_plan(make_company, wide_plan):
    company, admin, _ = make_company("E1", modules=["fleet"])
    with pytest.raises(ModuleConfigError) as e:
        enable_module(company, "nope", admin)
    assert code_of(e) == "module_unknown" and e.value.status_code == 400
    with pytest.raises(ModuleConfigError) as e:
        enable_module(company, "core", admin)
    assert code_of(e) == "module_core"
    Plan.objects.filter(code="start").update(modules=["fleet"])
    with pytest.raises(ModuleConfigError) as e:
        enable_module(company, "drivers", admin)
    assert code_of(e) == "module_not_in_plan" and e.value.status_code == 409
    assert state(company) == {"fleet"}


def test_enable_requires_dependencies_enabled(make_company, wide_plan):
    company, admin, _ = make_company("E2", modules=["fleet"])
    with pytest.raises(ModuleConfigError) as e:
        enable_module(company, "finance", admin)  # finance требует logistics
    assert code_of(e) == "module_requires" and e.value.detail["modules"] == ["logistics"]
    with pytest.raises(ModuleConfigError) as e:
        enable_module(company, "ocr", admin)  # ocr требует documents
    assert code_of(e) == "module_requires" and e.value.detail["modules"] == ["documents"]
    enable_module(company, "logistics", admin, "старт")
    enable_module(company, "finance", admin, "учёт")  # без экспедирования
    assert state(company) == {"fleet", "logistics", "finance"}


def test_documents_do_not_require_forwarding(make_company, wide_plan):
    company, admin, _ = make_company("E3", modules=["fleet"])
    enable_module(company, "documents", admin)  # без forwarding
    assert state(company) == {"fleet", "documents"}


def test_drivers_do_not_require_fleet_and_analytics_only_core(make_company, wide_plan):
    company, admin, _ = make_company("E4", modules=["forwarding"])
    enable_module(company, "drivers", admin)
    enable_module(company, "analytics", admin)
    assert {"drivers", "analytics"} <= state(company)


def test_enable_is_idempotent(make_company, wide_plan):
    company, admin, _ = make_company("E5", modules=["forwarding"])
    before = list(CompanyModule.all_objects.filter(company=company).values_list("id", flat=True))
    enable_module(company, "forwarding", admin)
    after = list(CompanyModule.all_objects.filter(company=company).values_list("id", flat=True))
    assert before == after


def test_disable_blocked_by_dependents_with_list(make_company, wide_plan):
    company, admin, _ = make_company("D1", modules=["forwarding"])
    with pytest.raises(ModuleConfigError) as e:
        disable_module(company, "logistics", admin, "хочу")
    assert code_of(e) == "module_has_dependents" and e.value.status_code == 409
    assert set(e.value.detail["modules"]) == {"finance", "forwarding"}
    assert state(company) == {"logistics", "forwarding", "finance", "documents"}
    disable_module(company, "forwarding", admin, "без экспедирования")  # свободно отключается
    assert "forwarding" not in state(company) and "logistics" in state(company)


def test_disable_cascade_disables_dependents_explicitly(make_company, wide_plan):
    company, admin, _ = make_company("D2", modules=["forwarding", "fleet"])
    enable_module(company, "drivers", admin)
    enable_module(company, "driver_app", admin)  # требует drivers и logistics
    disable_module(company, "logistics", admin, "не работаем с заказами", cascade=True)
    # forwarding, finance и driver_app зависят от logistics напрямую; documents и drivers - нет
    assert state(company) == {"fleet", "documents", "drivers"}
    from apps.core.audit.models import AuditLog

    with tenant_context(company.id):
        reasons = {
            a.changes["module_code"]: a.changes["reason"]
            for a in AuditLog.objects.filter(object_type="core.companymodule")
            if a.changes.get("enabled") == [True, False]
        }
    assert set(reasons) == {"forwarding", "finance", "driver_app"}
    assert "каскадно" in reasons["finance"] and "каскадно" not in reasons["forwarding"]


def test_cascade_is_transitive(make_company, wide_plan):
    company, admin, _ = make_company("D3", modules=["fleet"])
    enable_module(company, "gps", admin)  # gps требует fleet
    with pytest.raises(ModuleConfigError) as e:
        disable_module(company, "fleet", admin, "")
    assert code_of(e) == "module_has_dependents" and e.value.detail["modules"] == ["gps"]
    disable_module(company, "fleet", admin, "", cascade=True)
    assert state(company) == set()


def test_documents_can_be_disabled_with_forwarding_on(make_company, wide_plan):
    company, admin, _ = make_company("D4", modules=["forwarding"])
    disable_module(company, "documents", admin, "не нужны")
    assert state(company) == {"logistics", "forwarding", "finance"}


def test_ocr_blocks_documents_disable(make_company, wide_plan):
    company, admin, _ = make_company("D5", modules=["forwarding"])
    enable_module(company, "ocr", admin)
    with pytest.raises(ModuleConfigError) as e:
        disable_module(company, "documents", admin)
    assert code_of(e) == "module_has_dependents" and e.value.detail["modules"] == ["ocr"]


@pytest.mark.parametrize("engine", ["shadow", "new"])
def test_finance_protected_at_shadow_and_new(make_company, wide_plan, engine):
    company, admin, _ = make_company("P" + engine, modules=["forwarding"])
    extra = {}
    if engine == "new":  # CHECK в БД: new требует cutover_date и completed_status
        with tenant_context(company.id):
            extra = {
                "cutover_date": date(2026, 1, 1),
                "completed_status": HandbookValue.objects.get(
                    handbook__code="trip_status", code="COMPLETED"
                ),
            }
    CompanyFinancialSettings.all_objects.filter(company=company).update(engine=engine, **extra)
    with pytest.raises(ModuleConfigError) as e:
        disable_module(company, "finance", admin, "тест")
    assert code_of(e) == "module_protected" and e.value.detail["modules"] == ["finance"]
    assert "finance" in state(company)


def test_finance_protected_also_by_cascade_and_nothing_changed(make_company, wide_plan):
    company, admin, _ = make_company("PC", modules=["forwarding"])
    CompanyFinancialSettings.all_objects.filter(company=company).update(engine="shadow")
    with pytest.raises(ModuleConfigError) as e:
        disable_module(company, "logistics", admin, "всё", cascade=True)
    assert code_of(e) == "module_protected"
    assert state(company) == {"logistics", "forwarding", "finance", "documents"}  # без изменений


def test_finance_can_be_disabled_in_legacy(make_company, wide_plan):
    company, admin, _ = make_company("PL", modules=["forwarding"])
    disable_module(company, "finance", admin, "legacy")
    assert "finance" not in state(company)


def test_engine_new_check_is_covered_by_guard_function(make_company):
    from apps.finance.module_guard import PROTECTED_ENGINES, finance_disable_guard

    assert set(PROTECTED_ENGINES) == {"shadow", "new"}
    company, _, _ = make_company("G", modules=["forwarding"])
    assert finance_disable_guard(company) is None


def test_data_kept_and_reenable_restores_access(make_company, wide_plan):
    company, admin, api = make_company("DR", modules=["forwarding"])
    from apps.forwarding.models import Client

    with tenant_context(company.id):
        Client.objects.create(name="Клиент до отключения")
    assert api.get("/api/clients/").status_code == 200
    with tenant_context(company.id):
        row_id = CompanyModule.objects.get(module_code="documents").pk
    disable_module(company, "documents", admin, "тест")
    disable_module(company, "finance", admin, "тест")
    disable_module(company, "forwarding", admin, "тест")
    disable_module(company, "logistics", admin, "тест")
    resp = api.get("/api/clients/")
    assert resp.status_code == 403 and resp.json()["code"] == "module_disabled"
    with tenant_context(company.id):  # данные на месте
        assert Client.objects.filter(name="Клиент до отключения").exists()
    enable_module(company, "logistics", admin, "вернули")
    with tenant_context(company.id):
        assert CompanyModule.objects.filter(module_code="logistics").count() == 1
    enable_module(company, "documents", admin)
    with tenant_context(company.id):
        assert CompanyModule.objects.get(module_code="documents").pk == row_id
    resp = api.get("/api/clients/")
    assert resp.status_code == 200
    assert [c["name"] for c in resp.json()["results"]] == ["Клиент до отключения"]


def test_plan_change_does_not_touch_company_modules(make_company, wide_plan):
    company, admin, api = make_company("PCh", modules=["forwarding"])
    before = state(company)
    Plan.objects.filter(code="start").update(modules=["fleet"])
    assert state(company) == before  # конфигурация компании не меняется
    resp = api.get("/api/clients/")
    assert resp.status_code == 403 and resp.json()["code"] == "module_disabled"
    assert api.get("/api/session/").json()["modules"] == []
    Plan.objects.filter(code="start").update(modules=ALL_PLAN)  # вернули тариф - всё снова
    assert api.get("/api/clients/").status_code == 200
    assert state(company) == before


def test_describe_modules_reports_blockers(make_company, wide_plan):
    company, admin, _ = make_company("DM", modules=["forwarding"])
    items = {i["code"]: i for i in describe_modules(company)}
    assert items["core"]["enabled"] and not items["core"]["can_disable"]
    assert items["logistics"]["enabled"] and not items["logistics"]["can_disable"]
    assert items["logistics"]["blocker"]["code"] == "module_has_dependents"
    assert set(items["logistics"]["dependents"]) == {"finance", "forwarding"}
    assert items["forwarding"]["can_disable"]  # экспедирование отключается свободно
    assert items["documents"]["can_disable"] and items["documents"]["blocker"] is None
    assert items["fleet"]["can_enable"] and not items["fleet"]["enabled"]
    assert items["gps"]["blocker"]["code"] == "module_requires"
    Plan.objects.filter(code="start").update(
        modules=["logistics", "forwarding", "finance", "documents"]
    )
    items = {i["code"]: i for i in describe_modules(company)}
    assert items["fleet"]["blocker"]["code"] == "module_not_in_plan"
    assert items["fleet"]["available_in_plan"] is False


def test_companions_respect_plan_and_manual_disable():
    from apps.core.module_services import with_default_companions

    assert with_default_companions(["logistics"]) == ["logistics", "finance", "documents"]
    assert with_default_companions(["logistics"], allowed={"logistics", "documents"}) == [
        "logistics",
        "documents",
    ]
    assert with_default_companions(["logistics"], skip={"finance"}) == [
        "logistics",
        "documents",
    ]


def test_apply_profile_does_not_reenable_manually_disabled(make_company, wide_plan):
    from apps.core.models import ActivityProfile
    from apps.core.module_services import apply_profile

    company, admin, _ = make_company("Manual", modules=["forwarding"])
    disable_module(company, "documents", admin, "не нужны")  # решение владельца
    profile = ActivityProfile.objects.get(code="forwarder")
    result = apply_profile(company, profile, admin)
    skipped = {s["code"]: s["error_code"] for s in result["skipped"]}
    assert skipped == {"documents": "manually_disabled"}
    assert "documents" not in enabled_module_codes(company.id)


def test_carrier_without_forwarding_has_finance_and_logistics(make_company, wide_plan):
    company, admin, _ = make_company("Carrier", modules=["logistics", "fleet"])
    assert set(enabled_module_codes(company.id)) == {"logistics", "fleet", "finance", "documents"}
    assert "forwarding" not in enabled_module_codes(company.id)
