"""Каталог модулей (Module) и профилей деятельности (ActivityProfile) + посев.

Платформенные таблицы (без company и без RLS, как billing.Plan). Миграция самодостаточна:
константы каталога записаны здесь, код приложения не импортируется. Посев идемпотентен
(update_or_create по code); обратная миграция удаляет таблицы вместе с данными каталога.
Источник: архитектурное дополнение v1.1, разд. 2.2.
"""

from django.db import migrations, models


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
        "enhances": ["forwarding", "finance", "fleet", "drivers"],
        "status": "available",
    },
    {
        "code": "forwarding",
        "name": "Экспедирование",
        "description": "Клиенты, перевозчики, заказы, грузы, рейсы, участки, передачи",
        "sort": 30,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["documents", "finance", "fleet", "drivers", "gps"],
        "status": "available",
    },
    {
        "code": "finance",
        "name": "Финансы",
        "description": "Счета, оплаты, доходы, расходы, периоды, курсы",
        "sort": 40,
        "is_core": False,
        "requires": ["core", "forwarding"],
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
        "enhances": ["documents", "drivers", "forwarding", "gps"],
        "status": "available",
    },
    {
        "code": "drivers",
        "name": "Водители",
        "description": "Водители, документы, назначения",
        "sort": 60,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["documents", "fleet", "forwarding"],
        "status": "beta",
    },
    {
        "code": "driver_app",
        "name": "Приложение водителя",
        "description": "Мобильный интерфейс водителя",
        "sort": 70,
        "is_core": False,
        "requires": ["drivers", "forwarding"],
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
        "enhances": ["forwarding", "notifications"],
        "status": "beta",
    },
    {
        "code": "ocr",
        "name": "Распознавание документов",
        "description": "Распознавание документов",
        "sort": 90,
        "is_core": False,
        "requires": ["documents"],
        "enhances": ["finance", "forwarding"],
        "status": "beta",
    },
    {
        "code": "notifications",
        "name": "Уведомления",
        "description": "Центр уведомлений, Telegram",
        "sort": 100,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["forwarding", "finance", "fleet", "drivers", "documents", "gps"],
        "status": "beta",
    },
    {
        "code": "analytics",
        "name": "Аналитика",
        "description": "Отчёты, настраиваемый дашборд",
        "sort": 110,
        "is_core": False,
        "requires": ["core"],
        "enhances": ["forwarding", "finance", "fleet", "drivers"],
        "status": "beta",
    },
]

PROFILES = [
    {
        "code": "forwarder",
        "name": "Экспедитор",
        "description": "Экспедиторская компания: заказы, рейсы, финансы и документы",
        "modules": ["forwarding", "finance", "documents"],
    },
    {
        "code": "carrier",
        "name": "Перевозчик",
        "description": "Перевозчик со своим автопарком и водителями",
        "modules": ["forwarding", "fleet", "drivers", "documents"],
    },
    {
        "code": "forwarder_carrier",
        "name": "Экспедитор и перевозчик",
        "description": "Экспедитор со своим автопарком и водителями",
        "modules": ["forwarding", "finance", "documents", "fleet", "drivers"],
    },
]


def seed_catalog(apps, schema_editor):
    Module = apps.get_model("core", "Module")
    ActivityProfile = apps.get_model("core", "ActivityProfile")
    for data in MODULES:
        Module.objects.update_or_create(code=data["code"], defaults=data)
    for data in PROFILES:
        ActivityProfile.objects.update_or_create(code=data["code"], defaults=data)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_finance_architecture_permissions"),
    ]

    operations = [
        migrations.CreateModel(
            name="ActivityProfile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.SlugField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("modules", models.JSONField(blank=True, default=list)),
            ],
            options={
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="Module",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.SlugField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("sort", models.PositiveIntegerField(default=0)),
                ("is_core", models.BooleanField(default=False)),
                ("requires", models.JSONField(blank=True, default=list)),
                ("enhances", models.JSONField(blank=True, default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("available", "Доступен"),
                            ("beta", "Бета"),
                            ("retired", "Выведен"),
                        ],
                        default="available",
                        max_length=16,
                    ),
                ),
            ],
            options={
                "ordering": ["sort", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("status__in", ["available", "beta", "retired"])),
                        name="module_status_valid",
                    )
                ],
            },
        ),
        migrations.RunPython(seed_catalog, migrations.RunPython.noop),
    ]
