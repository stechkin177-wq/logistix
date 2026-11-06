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

# Особые права сверх сетки «раздел + действие»: обход лимита кредита и отмена счёта.
EXTRA_PERMISSIONS = ["finance.override_limit", "finance.cancel_invoice"]

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
    + EXTRA_PERMISSIONS
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
