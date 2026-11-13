"""Банковские счета сторон: единый источник (BankAccount) и зеркало в столбцах bank/iban владельца.

Столбцы bank/iban у клиента, перевозчика и юрлица остаются для прежних читателей (API сторон,
документы). Они - только зеркало счёта по умолчанию: после любого изменения счетов владельца
sync_mirror обновляет их в той же транзакции. Прежний путь записи (PATCH стороны с bank/iban)
превращается в счёт по умолчанию через upsert_default_from_legacy.
"""

from django.db import transaction

from apps.core.models import LegalEntity

from .models import BankAccount, Carrier, Client

OWNER_FIELD = {Client: "client", Carrier: "carrier", LegalEntity: "legal_entity"}


def owner_field(owner) -> str:
    for model, field in OWNER_FIELD.items():
        if isinstance(owner, model):
            return field
    raise TypeError(f"Нет банковских счетов у {type(owner).__name__}")


def accounts_of(owner):
    return BankAccount.objects.filter(**{owner_field(owner): owner})


def sync_mirror(owner) -> None:
    """Записывает bank/iban счёта по умолчанию в столбцы владельца (пусто, если счетов нет)."""
    default = accounts_of(owner).filter(is_default=True).first()
    bank, iban = (default.bank, default.iban) if default else ("", "")
    type(owner)._base_manager.filter(pk=owner.pk).update(bank=bank, iban=iban)
    owner.bank, owner.iban = bank, iban


def _ensure_default(owner) -> None:
    rest = accounts_of(owner)
    if rest.exists() and not rest.filter(is_default=True).exists():
        first = rest.order_by("id").first()
        BankAccount.objects.filter(pk=first.pk).update(is_default=True)


@transaction.atomic
def save_account(account: BankAccount, *, make_default: bool = False) -> BankAccount:
    """Сохраняет счёт: первый счёт владельца - по умолчанию; «по умолчанию» у владельца один."""
    owner = account.owner
    others = accounts_of(owner).exclude(pk=account.pk)
    if account._state.adding and not others.exists():
        account.is_default = True
    if make_default or account.is_default:
        others.filter(is_default=True).update(is_default=False)  # до записи: уникальность
        account.is_default = True
    account.save()
    _ensure_default(owner)
    sync_mirror(owner)
    return account


@transaction.atomic
def remove_account(account: BankAccount) -> None:
    owner = account.owner
    account.delete()
    _ensure_default(owner)
    sync_mirror(owner)


@transaction.atomic
def upsert_default_from_legacy(owner) -> None:
    """Прежняя запись bank/iban стороны -> счёт по умолчанию (создаётся или обновляется)."""
    bank, iban = owner.bank, owner.iban
    default = accounts_of(owner).filter(is_default=True).first()
    if default is None:
        if bank or iban:
            BankAccount.objects.create(
                **{owner_field(owner): owner}, bank=bank, iban=iban, is_default=True
            )
        return
    if (default.bank, default.iban) != (bank, iban):
        default.bank, default.iban = bank, iban
        default.save(update_fields=["bank", "iban"])
