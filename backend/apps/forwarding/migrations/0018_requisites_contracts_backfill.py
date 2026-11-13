"""Перенос в единые источники: банковские счета и договоры из прежних данных.

Ничего не удаляется и не меняется в прежних полях. Идемпотентна (повторный запуск не создаёт дублей).
- Счета: каждому клиенту, перевозчику и юрлицу с непустыми bank/iban - один счёт по умолчанию.
- Договоры: из выданных документов вида contract (клиент) и из уникальных пар (клиент, номер договора
  в заказе); заказам с совпавшим номером проставляется Order.contract (текст contract_number не
  меняется). Обратима как noop (созданные записи остаются; прежние поля не тронуты).
"""

from django.db import migrations

CONTRACT = "contract"


def _set_company(connection, company_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def _backfill_accounts(apps, company_id):
    BankAccount = apps.get_model("forwarding", "BankAccount")
    for model_label, field in (
        (("forwarding", "Client"), "client"),
        (("forwarding", "Carrier"), "carrier"),
        (("core", "LegalEntity"), "legal_entity"),
    ):
        model = apps.get_model(*model_label)
        for owner in model._base_manager.filter(company_id=company_id):
            if not (owner.bank or owner.iban):
                continue
            if BankAccount._base_manager.filter(company_id=company_id, **{field: owner}).exists():
                continue
            BankAccount._base_manager.create(
                company_id=company_id,
                **{field: owner},
                bank=owner.bank,
                iban=owner.iban,
                is_default=True,
            )


def _backfill_contracts(apps, company_id):
    Contract = apps.get_model("forwarding", "Contract")
    Order = apps.get_model("forwarding", "Order")
    IssuedDocument = apps.get_model("documents", "IssuedDocument")

    def find(client_id, number):
        return Contract._base_manager.filter(
            company_id=company_id, client_id=client_id, number=number, deleted_at__isnull=True
        ).first()

    linked = set(
        Contract._base_manager.filter(company_id=company_id, document__isnull=False).values_list(
            "document_id", flat=True
        )
    )
    docs = IssuedDocument._base_manager.filter(
        company_id=company_id, kind=CONTRACT, client__isnull=False
    ).order_by("id")
    for doc in docs:
        if doc.pk in linked:
            continue
        number = (doc.number or "").strip() or f"ДОК-{doc.id}"
        contract = find(doc.client_id, number)
        if contract is None:
            Contract._base_manager.create(
                company_id=company_id,
                client_id=doc.client_id,
                number=number,
                date=doc.issue_date,
                source="imported",
                title="Договор из выданных документов",
                document_id=doc.pk,
                created_by_id=doc.created_by_id,
            )
        elif contract.document_id is None:
            Contract._base_manager.filter(pk=contract.pk).update(document_id=doc.pk)

    pairs = (
        Order._base_manager.filter(company_id=company_id, contract__isnull=True)
        .exclude(contract_number="")
        .values_list("client_id", "contract_number")
        .distinct()
    )
    for client_id, raw_number in pairs:
        number = raw_number.strip()
        if not number:
            continue
        contract = find(client_id, number)
        if contract is None:
            first = (
                Order._base_manager.filter(
                    company_id=company_id, client_id=client_id, contract_number=raw_number
                )
                .order_by("created_at")
                .first()
            )
            contract = Contract._base_manager.create(
                company_id=company_id,
                client_id=client_id,
                number=number,
                date=first.created_at.date(),
                source="imported",
                title="Номер договора из заказов",
            )
        Order._base_manager.filter(
            company_id=company_id,
            client_id=client_id,
            contract_number=raw_number,
            contract__isnull=True,
        ).update(contract_id=contract.pk)


def forwards(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    connection = schema_editor.connection
    try:
        for company in Company.objects.all():
            _set_company(connection, company.id)
            _backfill_accounts(apps, company.id)
            _backfill_contracts(apps, company.id)
    finally:
        _set_company(connection, None)


class Migration(migrations.Migration):
    dependencies = [("forwarding", "0017_bank_accounts_contracts")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
