import importlib
import io

import pytest
from django.apps import apps as django_apps
from docx import Document

from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context
from apps.documents import catalog, engine
from apps.documents.models import KINDS, DocumentTemplate, DocumentTemplateVersion
from apps.documents.starter import DISCLAIMER, STARTER_NAMES, seed_starter_templates, starter_bytes

pytestmark = pytest.mark.django_db

KEY_VALUES = {
    "contract": ["ДОК-2026-001", 'ТОО "Пример"'],
    "order_request": ["З-2026-0042", 'ТОО "Пример"'],
    "carrier_order": ["ДОК-2026-001", "Р-2026-0017", 'ТОО "Пример"'],
    "act": ["ДОК-2026-001", 'ТОО "Пример"'],
    "invoice_print": ["СЧ-2026-0100", 'ТОО "Пример"'],
    "cmr": ["ДОК-2026-001", 'ТОО "Пример"'],
    "letter": ["ДОК-2026-001", 'ТОО "Пример"', "О сроках поставки"],
}


def render_text(kind, ctx=None):
    out = engine.render_docx(starter_bytes(kind), ctx or catalog.sample_context(kind))
    doc = Document(io.BytesIO(out))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_starter_passes_validation(kind):
    engine.validate_upload(starter_bytes(kind), kind)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_starter_renders_with_sample_context(kind):
    text = render_text(kind)
    for value in KEY_VALUES[kind]:
        assert value in text
    assert "{{" not in text and "{%" not in text


def test_names_cover_all_kinds():
    assert set(STARTER_NAMES) == set(KINDS)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_starter_contains_disclaimer(kind):
    doc = Document(io.BytesIO(starter_bytes(kind)))
    assert doc.paragraphs[0].text == DISCLAIMER


def check_complete(company):
    with tenant_context(company.id):
        templates = list(DocumentTemplate.objects.filter(language="ru"))
        assert {t.kind for t in templates} == set(KINDS)
        assert len(templates) == 7
        for t in templates:
            versions = list(DocumentTemplateVersion.objects.filter(template=t))
            assert len(versions) == 1 and versions[0].is_starter
            assert t.is_active and t.current_version_id == versions[0].id
            assert t.name == STARTER_NAMES[t.kind]


def test_seed_is_idempotent_and_complete(company):
    seed_starter_templates(company)
    seed_starter_templates(company)
    check_complete(company)


def test_new_company_gets_starter_set(django_user_model):
    owner = django_user_model.objects.create_user(email="st@example.com", password="pw-12345-xyz")
    created = create_company_with_defaults("Старт", owner, ["forwarding"])
    check_complete(created)


def test_backfill_seeds_existing_company_once(company):
    mod = importlib.import_module("apps.documents.migrations.0002_seed_starter_templates")
    with tenant_context(company.id):
        DocumentTemplate.objects.all().delete()
    mod.run_backfill(django_apps)
    mod.run_backfill(django_apps)
    check_complete(company)


def test_act_and_order_request_loops_render_all_rows():
    ctx = catalog.sample_context("act")
    ctx["invoice"]["items"] = [
        {"n": str(i), "title": f"Услуга-{i}", "amount_net": str(i * 100)} for i in range(1, 6)
    ]
    text = render_text("act", ctx)
    assert all(f"Услуга-{i}" in text for i in range(1, 6))

    ctx = catalog.sample_context("order_request")
    base = ctx["order"]["consignments"][0]
    ctx["order"]["consignments"] = [{**base, "name": f"Груз-{i}"} for i in range(1, 5)]
    text = render_text("order_request", ctx)
    assert all(f"Груз-{i}" in text for i in range(1, 5))
