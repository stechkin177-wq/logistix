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
]
ACTIONS = ["view", "create", "update", "delete"]

ALL_PERMISSIONS: list[str] = [f"{s}.{a}" for s in SECTIONS for a in ACTIONS]


def _codes(sections, actions):
    return [f"{s}.{a}" for s in sections for a in actions]


_OPERATIONS = ["clients", "carriers", "orders", "consignments", "trips"]
_VCU = ["view", "create", "update"]

SYSTEM_ROLES: dict[str, list[str]] = {
    "Администратор": list(ALL_PERMISSIONS),
    "Менеджер": _codes(_OPERATIONS, _VCU) + _codes(["finance", "trash", "handbooks"], ["view"]),
    "Бухгалтер": _codes(["finance"], ACTIONS) + _codes([*_OPERATIONS, "handbooks"], ["view"]),
    "Диспетчер": _codes(["orders", "consignments", "trips"], _VCU)
    + _codes(["clients", "carriers", "handbooks"], ["view"]),
    "Механик": ["trips.view"],
    "Наблюдатель": [p for p in ALL_PERMISSIONS if p.endswith(".view")],
    "Водитель": [],
}

ADMIN_ROLE_NAME = "Администратор"
