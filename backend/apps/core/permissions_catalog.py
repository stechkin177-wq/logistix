"""Каталог прав: коды вида "<раздел>.<действие>" и системные роли."""

SECTIONS = [
    "clients",
    "carriers",
    "orders",
    "consignments",
    "trips",
    "finance",
    "trash",
    "users",
    "roles",
    "company",
    "handbooks",
    "numbering",
    "documents",
]
ACTIONS = ["view", "create", "update", "delete"]

# Особые права сверх сетки «раздел + действие»: обход лимита кредита, отмена счёта, выход
# рейса из статуса «Завершён» (только Администратору) и права финансовой архитектуры.
FINANCE_EXTRA_PERMISSIONS = ["finance.override_limit", "finance.cancel_invoice"]
# Права финансовой архитектуры (периоды, обратное датирование, настройки). Отдельный список, а не
# FINANCE_EXTRA_PERMISSIONS: Бухгалтер получает только часть (ACCOUNTANT_FINANCE_PERMISSIONS).
FINANCE_ARCHITECTURE_PERMISSIONS = [
    "finance.close_period",
    "finance.reopen_period",
    "finance.adjust_closed",
    "finance.backdate",
    "finance.manage_settings",
]
ACCOUNTANT_FINANCE_PERMISSIONS = [
    "finance.close_period",
    "finance.adjust_closed",
    "finance.backdate",
]
EXTRA_PERMISSIONS = [
    *FINANCE_EXTRA_PERMISSIONS,
    "trips.revert_completed",
    *FINANCE_ARCHITECTURE_PERMISSIONS,
]

ALL_PERMISSIONS: list[str] = [f"{s}.{a}" for s in SECTIONS for a in ACTIONS] + EXTRA_PERMISSIONS


def _codes(sections, actions):
    return [f"{s}.{a}" for s in sections for a in actions]


_OPERATIONS = ["clients", "carriers", "orders", "consignments", "trips"]
_VCU = ["view", "create", "update"]

SYSTEM_ROLES: dict[str, list[str]] = {
    "Администратор": list(ALL_PERMISSIONS),
    "Менеджер": _codes(_OPERATIONS, _VCU)
    + _codes(["finance", "trash", "handbooks"], ["view"])
    + _codes(["documents"], ["view", "create"]),
    "Бухгалтер": _codes(["finance"], ACTIONS)
    + FINANCE_EXTRA_PERMISSIONS
    + ACCOUNTANT_FINANCE_PERMISSIONS
    + _codes([*_OPERATIONS, "handbooks"], ["view"])
    + _codes(["documents"], ["view", "create"]),
    "Диспетчер": _codes(["orders", "consignments", "trips"], _VCU)
    + _codes(["clients", "carriers", "handbooks"], ["view"])
    + _codes(["documents"], ["view", "create"]),
    "Механик": ["trips.view"],
    "Наблюдатель": [p for p in ALL_PERMISSIONS if p.endswith(".view")],
    "Водитель": [],
}

ADMIN_ROLE_NAME = "Администратор"
