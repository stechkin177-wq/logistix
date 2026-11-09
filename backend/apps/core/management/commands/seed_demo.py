# ruff: noqa: E501
"""Тестовая база с ВЫМЫШЛЕННЫМИ данными для локального знакомства с платформой.

Только для локальной разработки: команда отказывается работать при DEBUG=false и с БД не на
локальной машине. Данные создаются через обычный API платформы (те же проверки, права и правила),
поэтому ведут себя как рабочие. Все названия, имена и номера выдуманы; пароль и ключ TOTP - учебные.
"""

from __future__ import annotations

import datetime as dt
import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from rest_framework.test import APIClient

from apps.core import totp
from apps.core.api.auth import issue_tokens
from apps.core.models import ActivityProfile, Company, Membership, Role, User
from apps.core.module_services import VALID_MODULES
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context

DEMO_DOMAIN = "demo.local"
OWNER_EMAIL = f"owner@{DEMO_DOMAIN}"
COMPANY_A = "ИП Демо-Перевозчик (тест)"
COMPANY_B = "ТОО Демо-Экспедитор (тест)"
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def modules_of(profile_code: str) -> list[str]:
    profile = ActivityProfile.objects.get(code=profile_code)
    return [m for m in profile.modules if m in VALID_MODULES]


class Seeder:
    """Вызовы API от имени пользователя компании (в процессе, без сети)."""

    def __init__(self, user, company, stdout):
        self.client = APIClient(
            HTTP_HOST="localhost"
        )  # в демо-режиме (DEBUG=false) 'testserver' не разрешён
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id, mfa=True)['access']}"
        )
        self.stdout = stdout

    def call(self, method, url, body=None, ok=(200, 201, 204)):
        response = (
            getattr(self.client, method)(url, body, format="json")
            if body is not None
            else (getattr(self.client, method)(url))
        )
        if response.status_code not in ok:
            raise CommandError(
                f"{method.upper()} {url} -> {response.status_code}: {response.content[:300]!r}"
            )
        return response.json() if response.content else None

    def post(self, url, body):
        return self.call("post", url, body)

    def get(self, url):
        return self.call("get", url)


def iso(days: int, hour: int = 9) -> str:
    day = dt.datetime.now(dt.UTC).replace(hour=hour, minute=0, second=0, microsecond=0)
    return (day + dt.timedelta(days=days)).isoformat()


def date(days: int) -> str:
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


class Command(BaseCommand):
    help = (
        "Локальная тестовая БД с вымышленными данными: две компании, аккаунт владельца платформы и "
        "администратора первой компании (один аккаунт), сотрудники, клиенты, перевозчики, техника, "
        "водители, заказы и рейсы. Только DEBUG и локальная БД."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--password", default="Demo-pass-2026!", help="Учебный пароль всех аккаунтов"
        )
        parser.add_argument(
            "--remote-demo",
            action="store_true",
            help="Демо на внешней бесплатной БД: владелец без пароля и TOTP (одноразовая ссылка), "
            "остальные аккаунты - случайные пароли; требует DEMO_SEED_ALLOW_REF и DEMO_BASE_URL",
        )

    def _check_remote(self):
        """Демо-режим на внешней бесплатной БД: только с явным ключом и подтверждением базы."""
        ref = os.environ.get("DEMO_SEED_ALLOW_REF", "")
        user = connection.settings_dict.get("USER") or ""
        if not ref or not user.endswith(f".{ref}"):
            raise CommandError(
                "--remote-demo разрешён только для базы, явно названной в DEMO_SEED_ALLOW_REF "
                "(имя пользователя подключения должно заканчиваться на .<ref>)"
            )
        if not os.environ.get("DEMO_BASE_URL", "").startswith("https://"):
            raise CommandError("Для --remote-demo задайте DEMO_BASE_URL=https://<адрес интерфейса>")

    def handle(self, *args, password, remote_demo=False, **options):
        host = connection.settings_dict.get("HOST") or ""
        if remote_demo:
            self._check_remote()
        elif not settings.DEBUG or host not in LOCAL_HOSTS:
            raise CommandError(
                "seed_demo работает только с DJANGO_DEBUG=true и локальной БД (127.0.0.1/localhost)"
            )
        if User.objects.filter(email=OWNER_EMAIL).exists() or Company.objects.exists():
            raise CommandError(
                "В базе уже есть данные. Для чистого старта пересоздайте БД "
                "(docs/ops/LOCAL.md, раздел «Начать заново»)"
            )
        self.remote = remote_demo
        self.generated: dict[str, str] = {}  # логин -> случайный пароль (демо-режим)
        with transaction.atomic():  # при любой ошибке в базе не остаётся полуготовых данных
            secret = self._build(password)
        if remote_demo:
            self._print_remote()
        else:
            self._print(password, secret)

    def _build(self, password):
        secret = totp.new_secret()
        if self.remote:
            # владелец сам задаёт пароль по одноразовой ссылке и сам подключает TOTP при первом входе
            owner = User.objects.create_user(
                email=OWNER_EMAIL, password=None, full_name="Демо Владелец", platform_role="owner"
            )
            secret = ""
        else:
            owner = User.objects.create_user(
                email=OWNER_EMAIL, password=password, full_name="Демо Владелец",
                platform_role="owner", totp_secret=secret, totp_enabled=True,
            )  # fmt: skip
        admin_b = User.objects.create_user(
            email=f"admin@b.{DEMO_DOMAIN}",
            password=self._pw(f"admin@b.{DEMO_DOMAIN}", password),
            full_name="Демо Админ Б",
        )
        company_a = create_company_with_defaults(COMPANY_A, owner, modules_of("forwarder_carrier"))
        company_b = create_company_with_defaults(
            COMPANY_B, admin_b, modules_of("forwarder_carrier")
        )
        self._staff(company_a, password)
        self._company_a(owner, company_a)
        self._company_b(admin_b, company_b)
        return secret

    # --- сотрудники -------------------------------------------------------------------------

    def _pw(self, email, default):
        """Пароль аккаунта: в демо-режиме случайный (печатается один раз), иначе учебный."""
        if not self.remote:
            return default
        self.generated[email] = secrets.token_urlsafe(12) + "aZ9!"
        return self.generated[email]

    def _staff(self, company, password):
        for email, name, role_name in (
            (f"manager@{DEMO_DOMAIN}", "Демо Менеджер", "Менеджер"),
            (f"accountant@{DEMO_DOMAIN}", "Демо Бухгалтер", "Бухгалтер"),
        ):
            user = User.objects.create_user(
                email=email, password=self._pw(email, password), full_name=name
            )
            with tenant_context(company.id):
                role = Role.objects.get(name=role_name)
            Membership.objects.create(user=user, company=company, role=role, is_active=True)

    # --- компания А: перевозчик ---------------------------------------------------------------

    def _company_a(self, owner, company):
        api = Seeder(owner, company, self.stdout)
        clients = [
            api.post("/api/clients/", {"name": n})["id"]
            for n in ("ТОО Демо-Ромашка", "ТОО Демо-Стройсервис", "ИП Демо-Торг", "ТОО Демо-Агро")
        ]
        carriers = [
            api.post("/api/carriers/", {"name": n})["id"]
            for n in ("ИП Демо-Трансавто", "ТОО Демо-Логист", "ИП Демо-Дальнобой")
        ]
        vehicles = {
            plate: api.post("/api/vehicles/", {"kind": kind, "plate": plate, "make": make, "model": model, "year": year})["id"]
            for plate, kind, make, model, year in (
                ("111DEM01", "tractor", "Volvo", "FH", 2020),
                ("222DEM02", "tractor", "Scania", "R450", 2019),
                ("333DEM03", "truck", "КамАЗ", "5490", 2021),
                ("444DEM04", "trailer", "Schmitz", "S.KO", 2018),
                ("555DEM05", "trailer", "Krone", "SD", 2020),
            )
        }  # fmt: skip
        drivers = [
            api.post("/api/drivers/", {"full_name": n, "phone": p})["id"]
            for n, p in (
                ("Демо Сериков Ерлан", "+77010000001"),
                ("Демо Иванов Пётр", "+77010000002"),
                ("Демо Ахметов Нурлан", "+77010000003"),
            )
        ]
        self._documents(api, vehicles, drivers)
        self._fleet_records(api, vehicles)
        self._orders(api, clients, carriers, vehicles, drivers)

    def _types(self, api, subject):
        return {t["name"]: t["id"] for t in api.get(f"/api/document-types/?subject={subject}")}

    def _documents(self, api, vehicles, drivers):
        veh = self._types(api, "tractor")
        drv = self._types(api, "driver")
        # сроки подобраны, чтобы были и просроченные, и скоро истекающие, и спокойные
        for plate, days in (("111DEM01", 20), ("222DEM02", -5), ("333DEM03", 200)):
            api.post("/api/vehicle-documents/", {
                "vehicle": vehicles[plate], "doc_type": veh["Техосмотр"],
                "number": f"ТО-{plate}", "expires_at": date(days),
            })  # fmt: skip
        for driver_id, days in zip(drivers, (25, 400, -10), strict=True):
            api.post("/api/driver-documents/", {
                "driver": driver_id, "doc_type": drv["Водительское удостоверение"],
                "number": f"ВУ-{driver_id:04d}", "issued_by": "ЦОН (вымышленный)",
                "expires_at": date(days),
            })  # fmt: skip

    def _fleet_records(self, api, vehicles):
        v = vehicles["111DEM01"]
        for i, (days, liters, km) in enumerate(
            ((-40, 420, 100000), (-20, 380, 102800), (-5, 400, 105500))
        ):
            api.post("/api/fuel-fills/", {
                "vehicle": v, "filled_at": iso(days), "liters": str(liters),
                "odometer_km": km, "full_tank": True, "station": f"АЗС Демо-{i + 1}",
            })  # fmt: skip
        api.post(
            "/api/service-records/",
            {
                "vehicle": v,
                "kind": "maintenance",
                "status": "planned",
                "title": "Плановое ТО (демо)",
                "planned_date": date(12),
            },
        )

    def _order(self, api, client, rate, load, unload, name, days):
        order = api.post("/api/orders/", {
            "client": client, "client_rate": str(rate),
            "consignments": [{
                "name": name, "weight_kg": "12000", "volume_m3": "60",
                "points": [
                    {"kind": "load", "window_from": iso(days), "city": load},
                    {"kind": "unload", "window_from": iso(days + 2), "city": unload},
                ],
            }],
        })  # fmt: skip
        full = api.get(f"/api/orders/{order['id']}/")
        return full, full["consignments"][0]["id"]

    def _trip(self, api, cargo_id, **extra):
        return api.post("/api/trips/", {"consignments": [cargo_id], **extra})

    def _walk(self, api, trip_id, codes):
        statuses = {
            v["code"]: v["id"]
            for v in api.get("/api/handbooks/?code=trip_status")["values"]
            if v.get("code")
        }
        for code in codes:
            api.post(f"/api/trips/{trip_id}/status/", {"status": statuses[code]})

    def _order_status(self, api, order_id, name):
        values = api.get("/api/handbooks/?code=order_status")["values"]
        status = next(v["id"] for v in values if v["name"] == name)
        api.post(f"/api/orders/{order_id}/status/", {"status": status})

    def _orders(self, api, clients, carriers, vehicles, drivers):
        # 1. сценарий проверки legacy: клиент 250 000, перевозчик 180 000, расход перевозчику внесён
        order, cargo = self._order(
            api, clients[0], 250000, "Алматы", "Астана", "Станки (демо)", -12
        )
        trip = self._trip(
            api,
            cargo,
            carrier=carriers[0],
            carrier_price="180000",
            vehicle_plate="999DEM99",
            driver_name="Демо Водитель",
        )
        self._walk(api, trip["id"], ["ASSIGNED", "IN_PROGRESS", "UNLOADING", "COMPLETED"])
        self._order_status(api, order["id"], "Завершён")
        api.post(
            f"/api/finance/trips/{trip['id']}/expense-lines/",
            {"allocations": [{"order_id": order["id"], "amount": "180000.00"}]},
        )
        # 2. собственный рейс: своя техника и водитель, в пути
        order, cargo = self._order(
            api, clients[1], 420000, "Шымкент", "Караганда", "Стройматериалы (демо)", -2
        )
        trip = self._trip(
            api,
            cargo,
            vehicle=vehicles["111DEM01"],
            trailer=vehicles["444DEM04"],
            driver=drivers[0],
            carrier_price="0",
        )
        self._walk(api, trip["id"], ["ASSIGNED", "IN_PROGRESS"])
        self._order_status(api, order["id"], "В пути")
        # 3. запланированный рейс у привлечённого перевозчика
        order, cargo = self._order(
            api, clients[2], 300000, "Астана", "Актау", "Товары народного потребления (демо)", 3
        )
        self._trip(
            api,
            cargo,
            carrier=carriers[1],
            carrier_price="210000",
            vehicle_plate="888DEM88",
            driver_name="Демо Перевозчик",
        )
        # 4. заказы без рейса (очередь «Грузы без рейса»)
        for client, rate, load, unload, name, days in (
            (clients[3], 560000, "Костанай", "Павлодар", "Зерно (демо)", 5),
            (clients[0], 150000, "Алматы", "Тараз", "Оборудование (демо)", 7),
        ):
            self._order(api, client, rate, load, unload, name, days)

    # --- компания Б: экспедитор (для проверки изоляции) --------------------------------------

    def _company_b(self, admin, company):
        api = Seeder(admin, company, self.stdout)
        client = api.post("/api/clients/", {"name": "ТОО Демо-Клиент Б"})["id"]
        self._order(api, client, 100000, "Алматы", "Семей", "Груз компании Б (демо)", 1)

    def _print(self, password, secret):
        emails = {
            "Владелец платформы + Администратор компании А (один аккаунт)": OWNER_EMAIL,
            "Менеджер компании А": f"manager@{DEMO_DOMAIN}",
            "Бухгалтер компании А": f"accountant@{DEMO_DOMAIN}",
            "Администратор компании Б": f"admin@b.{DEMO_DOMAIN}",
        }
        self.stdout.write(self.style.SUCCESS("Тестовая БД создана (все данные вымышленные)."))
        for role, email in emails.items():
            self.stdout.write(f"  {email:<28} {role}")
        self.stdout.write(f"Пароль всех аккаунтов (учебный): {password}")
        self.stdout.write(
            f"Ключ TOTP владельца (для приложения-аутентификатора): {secret}\n"
            "Текущий код без телефона (только локально): python local/run.py totp  (или python manage.py demo_totp в backend/)"
        )

    def _print_remote(self):
        from apps.core import password_setup

        owner = User.objects.get(email=OWNER_EMAIL)
        link = password_setup.setup_url(owner, os.environ["DEMO_BASE_URL"])
        self.stdout.write(self.style.SUCCESS("ДЕМО-БАЗА СОЗДАНА (все данные вымышленные)"))
        self.stdout.write(f"OWNER_LINK={link}")
        for email, pw in self.generated.items():
            self.stdout.write(f"ACCOUNT {email} {pw}")
