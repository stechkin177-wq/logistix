from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.core.rls import tables_missing_rls
from apps.core.tenancy import tenant_context
from apps.documents.errors import DocumentError
from apps.documents.models import (
    KINDS,
    NUMBERED_KINDS,
    DocumentTemplate,
    DocumentTemplateVersion,
    IssuedDocument,
)

pytestmark = pytest.mark.django_db


def make_template(company, **extra):
    base = {"company": company, "kind": "act", "name": "Акт", "language": "ru"}
    base.update(extra)
    with tenant_context(company.id):
        return DocumentTemplate.objects.create(**base)


def make_version(company, template, number=1, **extra):
    base = {
        "company": company,
        "template": template,
        "number": number,
        "content": b"PK\x03\x04data",
        "sha256": "0" * 64,
    }
    base.update(extra)
    with tenant_context(company.id):
        return DocumentTemplateVersion.objects.create(**base)


def make_issued(company, template, **extra):
    version = make_version(company, template, number=extra.pop("vnum", 1))
    base = {
        "company": company,
        "kind": "act",
        "template_version": version,
        "number": "АКТ-2026-00001",
        "issue_date": date(2026, 11, 1),
        "language": "ru",
        "snapshot": {},
    }
    base.update(extra)
    with tenant_context(company.id):
        return IssuedDocument.objects.create(**base)


def test_constants():
    assert NUMBERED_KINDS == ["contract", "carrier_order", "act", "cmr", "letter"]
    assert set(NUMBERED_KINDS) < set(KINDS) and len(KINDS) == 7


def test_document_error():
    err = DocumentError("bad", "Плохо", 409)
    assert err.status_code == 409 and err.detail == "Плохо"
    assert DocumentError("bad", "x").status_code == 400


def test_one_active_template_per_kind_language(company):
    make_template(company)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_template(company, name="Акт 2")
    make_template(company, name="Акт en", language="en")
    make_template(company, name="Неактивный", is_active=False)


def test_version_number_unique_per_template(company):
    tpl = make_template(company)
    make_version(company, tpl, 1)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_version(company, tpl, 1)
    make_version(company, tpl, 2)


def test_version_content_not_empty(company):
    tpl = make_template(company)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_version(company, tpl, 1, content=b"")


def test_kind_must_be_known(company):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_template(company, kind="bogus")


def test_issued_number_unique_for_numbered_kinds(company):
    tpl = make_template(company)
    make_issued(company, tpl)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_issued(company, tpl, vnum=2)
    make_issued(company, tpl, kind="order_request", number="X-1", vnum=3)
    make_issued(company, tpl, kind="order_request", number="X-1", vnum=4)


def test_issued_document_has_snapshot_json(company):
    tpl = make_template(company)
    snap = {
        "order": {"consignments": [{"name": "Мука", "weight_kg": "1 500,50"}]},
        "doc": {"number": "АКТ-2026-00001"},
    }
    doc = make_issued(company, tpl, snapshot=snap)
    with tenant_context(company.id):
        assert IssuedDocument.objects.get(pk=doc.pk).snapshot == snap
    for bad in (Decimal("1.00"), date(2026, 11, 1)):
        with pytest.raises(TypeError), transaction.atomic():
            make_issued(company, tpl, kind="letter", number="П-1", vnum=5, snapshot={"a": bad})


def test_rls_tables_covered(company):
    assert tables_missing_rls() == []
