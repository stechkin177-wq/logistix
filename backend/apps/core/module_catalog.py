"""Код-реестр каталога модулей и профилей деятельности (архитектурное дополнение v1.1, разд. 2.2).

Единый источник для тестов и проверок целостности. Миграция core.0015 держит собственную копию
констант (миграции не импортируют код приложения); тест сверяет БД с этим реестром.
Жёсткая зависимость (requires) допускается только там, где модуль технически не может работать
без другого; обоснование каждой записано в REQUIRES_REASONS.
"""

CORE = "core"

# (code, name, description, sort, is_core, requires, enhances, status)
MODULES = [
    {
        "code": "core",
        "name": "Основа",
        "description": "Компании, пользователи, роли, справочники, нумерация, аудит, корзина",
        "sort": 10,
        "is_core": True,
        "requires": [],
        "enhances": [],
        "status": "available",
    },
    {
        "code": "documents",
        "name": "Документы",
        "description": "Шаблоны, выдача и журнал документов, вложения, снимки",
        "sort": 20,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["logistics", "forwarding", "finance", "fleet", "drivers"],
        "status": "available",
    },
    {
        "code": "logistics",
        "name": "Перевозки",
        "description": "Клиенты, заказы, грузы, остановки, рейсы, участки, передачи, простои",
        "sort": 25,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["documents", "finance", "fleet", "drivers", "gps", "forwarding"],
        "status": "available",
    },
    {
        "code": "forwarding",
        "name": "Экспедирование",
        "description": "Сторонние перевозчики, назначение рейсов и расходы перевозчикам",
        "sort": 30,
        "is_core": False,
        "requires": ["core", "logistics"],
        "enhances": ["documents", "finance", "fleet", "drivers", "gps"],
        "status": "available",
    },
    {
        "code": "finance",
        "name": "Финансы",
        "description": "Счета, оплаты, доходы, расходы, периоды, курсы",
        "sort": 40,
        "is_core": False,
        "requires": ["core", "logistics"],
        "enhances": ["documents"],
        "status": "available",
    },
    {
        "code": "fleet",
        "name": "Автопарк",
        "description": "Техника, обслуживание, ремонт, страхование",
        "sort": 50,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["documents", "drivers", "logistics", "forwarding", "gps"],
        "status": "available",
    },
    {
        "code": "drivers",
        "name": "Водители",
        "description": "Водители, документы, назначения",
        "sort": 60,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["documents", "fleet", "logistics", "forwarding"],
        "status": "beta",
    },
    {
        "code": "driver_app",
        "name": "Приложение водителя",
        "description": "Мобильный интерфейс водителя",
        "sort": 70,
        "is_core": False,
        "requires": ["drivers", "logistics"],
        "enhances": ["documents", "ocr", "gps"],
        "status": "beta",
    },
    {
        "code": "gps",
        "name": "GPS-мониторинг",
        "description": "Провайдеры, карта, геозоны",
        "sort": 80,
        "is_core": False,
        "requires": ["fleet"],
        "enhances": ["logistics", "forwarding", "notifications"],
        "status": "beta",
    },
    {
        "code": "ocr",
        "name": "Распознавание документов",
        "description": "Распознавание документов",
        "sort": 90,
        "is_core": False,
        "requires": ["documents"],
        "enhances": ["finance", "logistics", "forwarding"],
        "status": "beta",
    },
    {
        "code": "notifications",
        "name": "Уведомления",
        "description": "Центр уведомлений, Telegram",
        "sort": 100,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["logistics", "forwarding", "finance", "fleet", "drivers", "documents", "gps"],
        "status": "beta",
    },
    {
        "code": "analytics",
        "name": "Аналитика",
        "description": "Отчёты, настраиваемый дашборд",
        "sort": 110,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["logistics", "forwarding", "finance", "fleet", "drivers"],
        "status": "beta",
    },
]

# Обоснование жёстких зависимостей (кроме core): без них модуль технически не работает.
REQUIRES_REASONS = {
    (
        "finance",
        "logistics",
    ): "данные финансов (доход, расход, счета) обязательно ссылаются на заказы и рейсы",
    ("forwarding", "logistics"): "экспедирование работает поверх общих заказов и рейсов",
    ("driver_app", "drivers"): "интерфейс работает от имени водителя",
    ("driver_app", "logistics"): "интерфейс показывает рейсы",
    ("gps", "fleet"): "устройство привязывается к технике",
    ("ocr", "documents"): "распознавание обрабатывает вложения документов",
}

PROFILES = [
    {
        "code": "forwarder",
        "name": "Экспедитор",
        "description": "Экспедиторская компания: заказы, рейсы, финансы и документы",
        "modules": ["logistics", "forwarding", "finance", "documents"],
    },
    {
        "code": "carrier",
        "name": "Перевозчик",
        "description": "Перевозчик: свои заказы, рейсы, автопарк, водители и финансы без экспедирования",
        "modules": ["logistics", "finance", "fleet", "drivers", "documents"],
    },
    {
        "code": "forwarder_carrier",
        "name": "Экспедитор и перевозчик",
        "description": "Экспедитор со своим автопарком и водителями",
        "modules": ["logistics", "forwarding", "finance", "documents", "fleet", "drivers"],
    },
]


def module_codes() -> list[str]:
    return [m["code"] for m in MODULES]


def non_core_codes() -> set[str]:
    return {m["code"] for m in MODULES if not m["is_core"]}


def catalog_problems(modules=None) -> list[str]:
    """Проверка целостности каталога: ссылки на существующие модули, отсутствие циклов."""
    modules = MODULES if modules is None else modules
    by_code = {m["code"]: m for m in modules}
    problems = []
    for m in modules:
        for field in ("requires", "enhances"):
            for dep in m[field]:
                if dep not in by_code:
                    problems.append(f"{m['code']}.{field}: неизвестный модуль {dep}")
                if dep == m["code"]:
                    problems.append(f"{m['code']}.{field}: ссылка на себя")
    state: dict[str, int] = {}

    def visit(code, path):
        if state.get(code) == 2:
            return
        if state.get(code) == 1:
            problems.append("цикл зависимостей: " + " -> ".join([*path, code]))
            return
        state[code] = 1
        for dep in by_code[code]["requires"]:
            if dep in by_code:
                visit(dep, [*path, code])
        state[code] = 2

    for code in by_code:
        visit(code, [])
    return problems
