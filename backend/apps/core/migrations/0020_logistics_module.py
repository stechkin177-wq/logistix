"""Модуль logistics («Перевозки»): общий слой заказов, грузов, рейсов; forwarding - расширение.

Миграция самодостаточна (код приложения не импортируется), идемпотентна и обратима.
 - Каталог и профили приводятся к новому реестру (update_or_create по code).
 - Компаниям с включённым forwarding включается logistics (строка CompanyModule создаётся, если её
   нет; ранее отключённая вручную строка не включается повторно); проекция Company.modules
   дополняется. Данные не удаляются.
 - Откат: строки CompanyModule, созданные этой миграцией (маркер причины, enabled_by пуст),
   удаляются, logistics убирается из проекции, каталог возвращается к состоянию до миграции.
"""

from django.db import migrations

MODULES = [{'code': 'core',
  'name': 'Основа',
  'description': 'Компании, пользователи, роли, справочники, нумерация, аудит, корзина',
  'sort': 10,
  'is_core': True,
  'requires': [],
  'enhances': [],
  'status': 'available'},
 {'code': 'documents',
  'name': 'Документы',
  'description': 'Шаблоны, выдача и журнал документов, вложения, снимки',
  'sort': 20,
  'is_core': False,
  'requires': ['core'],
  'enhances': ['logistics', 'forwarding', 'finance', 'fleet', 'drivers'],
  'status': 'available'},
 {'code': 'logistics',
  'name': 'Перевозки',
  'description': 'Клиенты, заказы, грузы, остановки, рейсы, участки, передачи, простои',
  'sort': 25,
  'is_core': False,
  'requires': ['core'],
  'enhances': ['documents', 'finance', 'fleet', 'drivers', 'gps', 'forwarding'],
  'status': 'available'},
 {'code': 'forwarding',
  'name': 'Экспедирование',
  'description': 'Сторонние перевозчики, назначение рейсов и расходы перевозчикам',
  'sort': 30,
  'is_core': False,
  'requires': ['core', 'logistics'],
  'enhances': ['documents', 'finance', 'fleet', 'drivers', 'gps'],
  'status': 'available'},
 {'code': 'finance',
  'name': 'Финансы',
  'description': 'Счета, оплаты, доходы, расходы, периоды, курсы',
  'sort': 40,
  'is_core': False,
  'requires': ['core', 'logistics'],
  'enhances': ['documents'],
  'status': 'available'},
 {'code': 'fleet',
  'name': 'Автопарк',
  'description': 'Техника, обслуживание, ремонт, страхование',
  'sort': 50,
  'is_core': False,
  'requires': ['core'],
  'enhances': ['documents', 'drivers', 'logistics', 'forwarding', 'gps'],
  'status': 'available'},
 {'code': 'drivers',
  'name': 'Водители',
  'description': 'Водители, документы, назначения',
  'sort': 60,
  'is_core': False,
  'requires': ['core'],
  'enhances': ['documents', 'fleet', 'logistics', 'forwarding'],
  'status': 'beta'},
 {'code': 'driver_app',
  'name': 'Приложение водителя',
  'description': 'Мобильный интерфейс водителя',
  'sort': 70,
  'is_core': False,
  'requires': ['drivers', 'logistics'],
  'enhances': ['documents', 'ocr', 'gps'],
  'status': 'beta'},
 {'code': 'gps',
  'name': 'GPS-мониторинг',
  'description': 'Провайдеры, карта, геозоны',
  'sort': 80,
  'is_core': False,
  'requires': ['fleet'],
  'enhances': ['logistics', 'forwarding', 'notifications'],
  'status': 'beta'},
 {'code': 'ocr',
  'name': 'Распознавание документов',
  'description': 'Распознавание документов',
  'sort': 90,
  'is_core': False,
  'requires': ['documents'],
  'enhances': ['finance', 'logistics', 'forwarding'],
  'status': 'beta'},
 {'code': 'notifications',
  'name': 'Уведомления',
  'description': 'Центр уведомлений, Telegram',
  'sort': 100,
  'is_core': False,
  'requires': ['core'],
  'enhances': ['logistics', 'forwarding', 'finance', 'fleet', 'drivers', 'documents', 'gps'],
  'status': 'beta'},
 {'code': 'analytics',
  'name': 'Аналитика',
  'description': 'Отчёты, настраиваемый дашборд',
  'sort': 110,
  'is_core': False,
  'requires': ['core'],
  'enhances': ['logistics', 'forwarding', 'finance', 'fleet', 'drivers'],
  'status': 'beta'}]

PROFILES = [{'code': 'forwarder',
  'name': 'Экспедитор',
  'description': 'Экспедиторская компания: заказы, рейсы, финансы и документы',
  'modules': ['logistics', 'forwarding', 'finance', 'documents']},
 {'code': 'carrier',
  'name': 'Перевозчик',
  'description': 'Перевозчик: свои заказы, рейсы, автопарк, водители и финансы',
  'modules': ['logistics', 'finance', 'fleet', 'drivers', 'documents']},
 {'code': 'forwarder_carrier',
  'name': 'Экспедитор и перевозчик',
  'description': 'Экспедитор со своим автопарком и водителями',
  'modules': ['logistics', 'forwarding', 'finance', 'documents', 'fleet', 'drivers']}]

# Состояние до миграции (для отката): code -> (requires, enhances, name, description, sort)
PREVIOUS = {
    "forwarding": (
        ["core"],
        ["documents", "finance", "fleet", "drivers", "gps"],
        "Экспедирование",
        "Клиенты, перевозчики, заказы, грузы, рейсы, участки, передачи",
        30,
    ),
    "finance": (["core", "forwarding"], ["documents"], None, None, None),
    "driver_app": (["drivers", "forwarding"], ["documents", "ocr", "gps"], None, None, None),
}
PREVIOUS_PROFILES = {
    "forwarder": ["forwarding", "finance", "documents"],
    "carrier": ["forwarding", "fleet", "drivers", "documents"],
    "forwarder_carrier": ["forwarding", "finance", "documents", "fleet", "drivers"],
}
MARKER = "Миграция core.0020: logistics включён вместе с forwarding"


def _set_company(connection, company_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def seed(apps, schema_editor):
    from django.utils import timezone

    Module = apps.get_model("core", "Module")
    ActivityProfile = apps.get_model("core", "ActivityProfile")
    for data in MODULES:
        Module.objects.update_or_create(code=data["code"], defaults=data)
    for data in PROFILES:
        ActivityProfile.objects.update_or_create(code=data["code"], defaults=data)
    Company = apps.get_model("core", "Company")
    CompanyModule = apps.get_model("core", "CompanyModule")
    connection = schema_editor.connection
    now = timezone.now()
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            rows = {
                r.module_code: r for r in CompanyModule._base_manager.filter(company_id=company.id)
            }
            fwd = rows.get("forwarding")
            if fwd is None or not fwd.enabled or "logistics" in rows:
                continue
            CompanyModule._base_manager.create(
                company_id=company.id,
                module_code="logistics",
                enabled=True,
                enabled_at=now,
                reason=MARKER,
            )
            modules = list(company.modules or [])
            if "logistics" not in modules:
                company.modules = [*modules, "logistics"]
                company.save(update_fields=["modules"])
    finally:
        _set_company(connection, None)


def unseed(apps, schema_editor):
    Module = apps.get_model("core", "Module")
    ActivityProfile = apps.get_model("core", "ActivityProfile")
    Company = apps.get_model("core", "Company")
    CompanyModule = apps.get_model("core", "CompanyModule")
    connection = schema_editor.connection
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            created = CompanyModule._base_manager.filter(
                company_id=company.id, module_code="logistics", enabled_by__isnull=True, reason=MARKER
            )
            if created.exists():
                company.modules = [m for m in (company.modules or []) if m != "logistics"]
                company.save(update_fields=["modules"])
                created.delete()
    finally:
        _set_company(connection, None)
    for code, (requires, enhances, name, description, sort) in PREVIOUS.items():
        values = {"requires": requires, "enhances": enhances}
        if name:
            values.update(name=name, description=description, sort=sort)
        Module.objects.filter(code=code).update(**values)
    for code, modules in PREVIOUS_PROFILES.items():
        ActivityProfile.objects.filter(code=code).update(modules=modules)
    Module.objects.filter(code="logistics").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0019_transfer_permission")]
    operations = [migrations.RunPython(seed, unseed)]
