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
    "drivers",
    "fleet",
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
# Права модульной архитектуры (этап 1.5-A): отдельный список, не входит в общие extra-списки.
# company.manage_modules - включение и отключение модулей компании (по умолчанию только
# Администратор; другим ролям назначается штатно, как trips.revert_completed).
MODULE_MANAGEMENT_PERMISSIONS = ["company.manage_modules"]
# Право передач груза (этап 1.5-D): подтверждение передачи/сторно. Отдельный список, не входит в
# общие extra-списки; по умолчанию Администратор, Менеджер, Диспетчер. Инициировать передачу можно
# с consignments.transfer или consignments.update.
TRANSFER_PERMISSIONS = ["consignments.transfer"]

# Право на журнал аудита и входов (раньше чтение журнала требовало company.view). Отдельный код,
# чтобы менеджеру можно было открыть историю своих записей, не давая доступ к настройкам.
# Не входит в «Наблюдатель» (там все *.view): аудит - не для наблюдателя по умолчанию.
AUDIT_PERMISSIONS = ["audit.view"]

# Метки: создание, правка и удаление меток компании. Назначать метки может тот, кто правит объект
# (раздел.update); видеть - тот, кто видит объект.
LABEL_PERMISSIONS = ["labels.manage"]

# Исходящая почта (apps.mail): просмотр писем, отправка, настройка ящика компании. Наблюдателю по
# умолчанию не выдаётся (переписка - персональные данные).
MAIL_PERMISSIONS = ["mail.view", "mail.send", "mail.manage_account"]

ALL_PERMISSIONS: list[str] = (
    [f"{s}.{a}" for s in SECTIONS for a in ACTIONS]
    + EXTRA_PERMISSIONS
    + MODULE_MANAGEMENT_PERMISSIONS
    + TRANSFER_PERMISSIONS
    + AUDIT_PERMISSIONS
    + LABEL_PERMISSIONS
    + MAIL_PERMISSIONS
)


def _codes(sections, actions):
    return [f"{s}.{a}" for s in sections for a in actions]


_OPERATIONS = ["clients", "carriers", "orders", "consignments", "trips"]
_VCU = ["view", "create", "update"]

SYSTEM_ROLES: dict[str, list[str]] = {
    "Администратор": list(ALL_PERMISSIONS),
    "Менеджер": _codes(_OPERATIONS, _VCU)
    + LABEL_PERMISSIONS
    + MAIL_PERMISSIONS[:2]
    + TRANSFER_PERMISSIONS
    + _codes(["finance", "trash", "handbooks", "drivers", "fleet"], ["view"])
    + _codes(["documents"], ["view", "create"]),
    "Бухгалтер": _codes(["finance"], ACTIONS)
    + FINANCE_EXTRA_PERMISSIONS
    + ACCOUNTANT_FINANCE_PERMISSIONS
    + _codes([*_OPERATIONS, "handbooks"], ["view"])
    + _codes(["documents"], ["view", "create"]),
    "Диспетчер": _codes(["orders", "consignments", "trips"], _VCU)
    + LABEL_PERMISSIONS
    + MAIL_PERMISSIONS[:2]
    + TRANSFER_PERMISSIONS
    + _codes(["clients", "carriers", "handbooks", "drivers", "fleet"], ["view"])
    + _codes(["documents"], ["view", "create"]),
    "Механик": ["trips.view", *_codes(["fleet"], _VCU)],
    "Наблюдатель": [
        p
        for p in ALL_PERMISSIONS
        if p.endswith(".view") and p not in AUDIT_PERMISSIONS and p != "mail.view"
    ],
    "Водитель": [],
}

ADMIN_ROLE_NAME = "Администратор"
