"""A1: каталог модулей и профили деятельности (платформенные таблицы, посев миграцией)."""

import pytest

from apps.core import module_catalog as registry
from apps.core.models import ActivityProfile, Module

pytestmark = pytest.mark.django_db


def test_catalog_seeded_exactly_as_registry():
    rows = {m.code: m for m in Module.objects.all()}
    assert set(rows) == set(registry.module_codes())
    assert len(rows) == 11
    for spec in registry.MODULES:
        row = rows[spec["code"]]
        assert row.requires == spec["requires"], spec["code"]
        assert row.enhances == spec["enhances"], spec["code"]
        assert row.is_core == spec["is_core"]
        assert row.status == spec["status"]
        assert row.sort == spec["sort"]


def test_only_core_is_core():
    assert list(Module.objects.filter(is_core=True).values_list("code", flat=True)) == ["core"]


def test_requirements_follow_addendum_table():
    by = {m.code: m for m in Module.objects.all()}
    assert by["documents"].requires == ["core"]  # документы НЕ требуют forwarding
    assert "forwarding" not in by["documents"].requires
    assert by["forwarding"].requires == ["core"]
    assert set(by["finance"].requires) == {"core", "forwarding"}
    assert by["fleet"].requires == ["core"]
    assert by["drivers"].requires == ["core"]  # drivers не требует fleet
    assert set(by["driver_app"].requires) == {"drivers", "forwarding"}
    assert by["gps"].requires == ["fleet"]
    assert by["ocr"].requires == ["documents"]
    assert by["notifications"].requires == ["core"]
    assert by["analytics"].requires == ["core"]  # analytics требует только core
    assert set(by["documents"].enhances) == {"forwarding", "finance", "fleet", "drivers"}
    assert by["finance"].enhances == ["documents"]


def test_catalog_has_no_cycles_and_dangling_requirements_in_db():
    rows = [
        {"code": m.code, "requires": m.requires, "enhances": m.enhances}
        for m in Module.objects.all()
    ]
    assert registry.catalog_problems(rows) == []
    assert registry.catalog_problems() == []


def test_catalog_problems_detect_cycle_and_unknown():
    bad = [
        {"code": "a", "requires": ["b"], "enhances": []},
        {"code": "b", "requires": ["a"], "enhances": []},
    ]
    assert any("цикл" in p for p in registry.catalog_problems(bad))
    dangling = [{"code": "a", "requires": ["zzz"], "enhances": []}]
    assert any("неизвестный модуль zzz" in p for p in registry.catalog_problems(dangling))
    selfref = [{"code": "a", "requires": ["a"], "enhances": []}]
    assert registry.catalog_problems(selfref)


def test_every_hard_dependency_has_a_reason():
    for spec in registry.MODULES:
        for dep in spec["requires"]:
            if dep != "core":
                assert (spec["code"], dep) in registry.REQUIRES_REASONS, (spec["code"], dep)


def test_activity_profiles_seeded():
    profiles = {p.name: p.modules for p in ActivityProfile.objects.all()}
    assert profiles["Экспедитор"] == ["forwarding", "finance", "documents"]
    assert profiles["Перевозчик"] == ["forwarding", "fleet", "drivers", "documents"]
    assert set(profiles["Экспедитор и перевозчик"]) == {
        "forwarding",
        "finance",
        "documents",
        "fleet",
        "drivers",
    }
    known = set(registry.module_codes())
    for modules in profiles.values():
        assert set(modules) <= known


def test_platform_tables_have_no_company_column():
    for model in (Module, ActivityProfile):
        assert "company" not in {f.name for f in model._meta.get_fields()}
