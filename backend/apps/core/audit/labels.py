"""Подписи полей в журнале аудита для пользователя: object_type -> {ключ changes: подпись}.

Старые записи не переписываются: в них остаётся прежний ключ (price), новые пишут новый
(carrier_price); подпись у обоих одинаковая.
"""

FIELD_LABELS: dict[str, dict[str, str]] = {
    "core.companymodule": {
        "module_code": "Модуль",
        "enabled": "Включён",
        "reason": "Причина",
    },
    "forwarding.trip": {
        "price": "К оплате перевозчику",
        "carrier_price": "К оплате перевозчику",
        "completed_at": "Дата завершения",
        "status_id": "Статус",
        "reason": "Причина",
    },
}


def changes_labels(object_type: str, changes) -> dict[str, str]:
    """Подписи только для ключей changes, которые есть в справочнике подписей."""
    labels = FIELD_LABELS.get(object_type, {})
    if not isinstance(changes, dict):
        return {}
    return {key: labels[key] for key in changes if key in labels}
