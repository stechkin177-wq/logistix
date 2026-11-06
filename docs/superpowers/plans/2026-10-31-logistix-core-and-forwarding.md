# Logistix: ядро и экспедиторский контур — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Рабочая мультитенантная платформа Logistix: компании, пользователи, роли, справочники, нумерация, тарифы с лимитами, а поверх них заказы, грузы и рейсы экспедитора с дашбордом, канбаном и корзиной.

**Architecture:** Модульный монолит Django (модули `core`, `billing`, `forwarding`) плюс SPA на React. Изоляция компаний через менеджер по умолчанию и RLS в PostgreSQL. Все пути ниже относятся к корню нового репозитория `logistix/`.

**Tech Stack:** Python 3.12, Django 5, DRF, simplejwt, PostgreSQL 16, Redis, Celery (подключается, задач пока нет), pytest, pytest-django, factory_boy, openpyxl; React 19, TypeScript, Vite, Tailwind, TanStack Query, React Router, i18next; Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-31-universal-logistics-platform-design.md` (временно лежит в репозитории `truck365`, первым коммитом переносится в `logistix/docs/`).

## Global Constraints

- Бэкенд: Django 5, DRF, PostgreSQL; фронтенд: React, TypeScript, Vite, Tailwind, TanStack Query, React Router. Тексты только через i18n, языки `ru` и `kk`, по умолчанию `ru`.
- Деньги только `Decimal` (`max_digits=14, decimal_places=2`), валюта хранится кодом справочника (`KZT`, `RUB`, `USD`, `EUR`).
- Данные только в Казахстане (hoster.kz); зарубежных реплик нет; Sentry настраивается с `send_default_pii=False`.
- Системные роли: Администратор, Менеджер, Наблюдатель, Бухгалтер, Диспетчер, Механик, Водитель.
- Право = `"<раздел>.<действие>"`, разделы: `clients carriers orders consignments trips finance trash users roles company handbooks numbering`, действия: `view create update delete`.
- Статусы заказа: Новый, В работе, На погрузке, В пути, На выгрузке, Завершён, Отменён (начальный Новый, конечные Завершён и Отменён). Статусы груза: Принят, На складе, В пути, Доставлен, Выдан. Статусы рейса: Планируется, Ожидает выезда, В пути, Выгрузка, Завершён, Отменён.
- Шаблоны нумерации по умолчанию: заказ `ORD-{year}-{index}` (5 цифр), рейс `{order}-{n}`, консолидированный рейс `C{index}`, выставленный счёт `СЧ-{year}-{index}` (5 цифр).
- Подписка: статусы `trial | active | grace | readonly | blocked`. Решение плана (в спецификации сроков нет): после окончания срока 14 дней `grace`, затем 30 дней `readonly` (только чтение), затем `blocked`. Первый год при создании компании выдаётся бесплатно: `is_free_period=True`, `ends_at = now + 365 дней`.
- Мягкое удаление для клиентов, перевозчиков, заказов, грузов, рейсов; удалённое видно только в корзине.
- Каждый клиентский эндпоинт покрыт тестом изоляции компаний.
- Коммиты на русском, формат «Что сделано».

## Review Focus

- Запрос чужого объекта по угаданному id (заказ другой компании) возвращает 404, а не 403 и не данные.
- Два одновременных создания заказа получают разные номера без пропусков и дублей.
- Подписка `readonly`: чтение работает, любая запись возвращает 403 с кодом `subscription_readonly`; `blocked`: вход запрещён.
- Заказ с нулевой выручкой даёт маржу `null`, а не деление на ноль; заказ без строк и без грузов не ломает дашборд.
- Телефоны `8 700 111 22 33`, `+7(700)1112233`, `7001112233` приводятся к `+77001112233`, а `12345` отклоняется понятной ошибкой.

---

### Task 1: Каркас репозитория, CI, health

**Files:**
- Create: `backend/manage.py`, `backend/config/{settings,urls,wsgi,celery}.py`, `backend/apps/core/{__init__,views}.py`, `backend/pyproject.toml`, `backend/pytest.ini`, `backend/conftest.py`
- Create: `docker-compose.yml` (postgres 16, redis 7), `.env.example`, `.github/workflows/ci.yml`, `README.md`
- Move: спецификация в `docs/superpowers/specs/`
- Test: `backend/apps/core/tests/test_health.py`

**Interfaces:**
- Produces: `GET /api/health/` → `{"status": "ok"}`; настройка `ATOMIC_REQUESTS=True`; `AUTH_USER_MODEL="core.User"`; константы окружения в `.env.example`.

- [ ] **Step 1: Создать репозиторий.** Нужен пустой репозиторий `logistix` (создаёт владелец или я по его разрешению). Склонировать, скопировать спецификацию и план в `docs/`.
- [ ] **Step 2: Failing-тест** `test_health_returns_ok`: `client.get("/api/health/")` даёт 200 и `{"status": "ok"}`.
- [ ] **Step 3: Запустить** `cd backend && pytest -q`, ожидать падение (нет проекта).
- [ ] **Step 4: Реализовать** проект Django с настройками из переменных окружения, DRF, simplejwt, `corsheaders`; `health` во view `core.views.health`. CI: job `backend` (postgres service, `pytest`, `ruff check`) и job `web` (после Task 15).
- [ ] **Step 5: Запустить** `pytest -q`, ожидать PASS; `docker compose up -d` поднимает БД.
- [ ] **Step 6: Commit** `Каркас проекта Logistix и проверка health`.

### Task 2: Компания и изоляция по компании

**Files:**
- Create: `backend/apps/core/{models,tenancy,managers}.py`, `backend/apps/core/migrations/0001_initial.py`
- Test: `backend/apps/core/tests/test_tenancy.py`

**Interfaces:**
- Produces:
  - `Company(name, bin, modules: list[str] default ["forwarding"], timezone, language, created_at)`; `LegalEntity(TenantModel: name, bin, bank, iban, address, is_default)`.
  - `core.tenancy`: `get_current_company_id() -> int | None`, `set_current_company(company_id: int | None) -> None`, `class NoTenantContext(Exception)`.
  - `TenantModel` (abstract): `company FK`, `objects = TenantManager()` (фильтрует по текущей компании, без контекста бросает `NoTenantContext`), `all_objects = models.Manager()`; `save()` подставляет компанию из контекста.
  - `SoftDeleteModel` (abstract): `deleted_at`, `delete()` помечает, менеджер `objects` скрывает удалённые, `trash` показывает только удалённые, `restore()`.

- [ ] **Step 1: Failing-тесты** в `test_tenancy.py`: (а) запись создаётся с компанией из контекста; (б) в контексте компании A запись компании B не видна; (в) без контекста `Model.objects.all()` бросает `NoTenantContext`; (г) `SoftDeleteModel.delete()` прячет запись, `restore()` возвращает.
- [ ] **Step 2: Запустить** `pytest apps/core/tests/test_tenancy.py -v`, ожидать FAIL.
- [ ] **Step 3: Реализовать** `contextvars.ContextVar` в `tenancy.py`, менеджеры в `managers.py`, абстрактные модели в `models.py` (для тестов использовать тестовую конкретную модель в `core/tests/models.py`).
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Компания и изоляция данных по компании`.

### Task 3: Пользователи, телефон, вход

**Files:**
- Create: `backend/apps/core/{phone,auth}.py`, `backend/apps/core/api/auth.py`; изменить `models.py`
- Test: `backend/apps/core/tests/test_phone.py`, `test_auth.py`

**Interfaces:**
- Consumes: `Company`, `set_current_company` (Task 2).
- Produces:
  - `core.phone.normalize_phone(raw: str) -> str` (возвращает `+7XXXXXXXXXX`, иначе `ValueError`).
  - `User(email unique null, phone unique null, full_name, is_platform_admin)`; `Membership(user, company, department null, role, is_active)`, `unique(user, company)`.
  - `POST /api/auth/login/` `{login, password}` → `{access, refresh, companies:[{id,name}]}`; токен содержит `company_id` выбранной (первой) компании; `POST /api/auth/switch-company/` `{company_id}`.
  - `CompanyJWTAuthentication` (DRF): проверяет членство и вызывает `set_current_company(company_id)`.

- [ ] **Step 1: Failing-тесты:** `normalize_phone("8 700 111 22 33") == "+77001112233"`, `("+7(700)1112233")`, `("7001112233")` дают тот же результат; `normalize_phone("12345")` бросает `ValueError`; вход по email и по телефону работает; вход в чужую компанию через `switch-company` даёт 403; пользователь без членства не получает токен.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** модели и сериализаторы; вход принимает `login` и определяет тип по наличию `@`.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Пользователи, телефоны и вход с выбором компании`.

### Task 4: Роли и права

**Files:**
- Create: `backend/apps/core/{permissions_catalog,api_permissions,services}.py`, `backend/apps/core/api/roles.py`
- Test: `backend/apps/core/tests/test_roles.py`

**Interfaces:**
- Consumes: `Membership`, `TenantModel`.
- Produces:
  - `Department(TenantModel: name)`, `Role(TenantModel: name, is_system, permissions: list[str])`.
  - `permissions_catalog.ALL_PERMISSIONS: list[str]`, `SYSTEM_ROLES: dict[str, list[str]]` (Администратор получает все права; Наблюдатель только `*.view`; остальные роли по смыслу).
  - `api_permissions.permission_required(code: str) -> type[BasePermission]`.
  - `core.services.create_company_with_defaults(name: str, owner: User, modules: list[str]) -> Company` (создаёт компанию, роли, юрлицо по умолчанию, членство владельца с ролью Администратор; справочники, нумерация и подписка подключаются в Tasks 5–7).
  - API `roles` (список, создание, изменение собственных ролей; системные не удаляются), `users` (приглашение и привязка членства).

- [ ] **Step 1: Failing-тесты:** созданная компания имеет 7 системных ролей; менеджер без `orders.create` получает 403 при создании заказа (тестовый эндпоинт); системную роль нельзя удалить (400); роль компании A не видна компании B.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** каталог прав и фабрику класса `permission_required`; проверка идёт по роли членства из токена.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Роли, права и создание компании по умолчанию`.

### Task 5: Режимы, тарифы, подписка и лимиты

**Files:**
- Create: `backend/apps/billing/{models,services,permissions}.py`, `backend/apps/billing/migrations/`, `backend/apps/billing/api.py`
- Modify: `core/services.py` (подписка при создании компании), `api_permissions.py`
- Test: `backend/apps/billing/tests/test_subscription.py`

**Interfaces:**
- Consumes: `Company.modules`, `create_company_with_defaults`.
- Produces:
  - `Plan(code, name, billing_type: monthly|yearly|lifetime, limits: dict, modules: list[str], options: dict, is_active)`; `Subscription(company OneToOne, plan, status, starts_at, ends_at null, is_free_period)`.
  - `billing.services.effective_status(sub: Subscription, now: datetime) -> str` по правилам из Global Constraints (у `lifetime` и `ends_at=None` всегда `active`).
  - `billing.services.check_limit(company: Company, key: str, current: int) -> None`, бросает `LimitExceeded` (HTTP 402, код `limit_exceeded`) при `current >= limits[key]`.
  - `ModuleRequired(module: str)` и `SubscriptionGate` (DRF permission, применяется глобально): `readonly` разрешает только безопасные методы, код `subscription_readonly`; `blocked` даёт 403 `subscription_blocked`.
  - Планы по умолчанию через миграцию данных: `start` (monthly), `business` (yearly), `lifetime`; цены не хранятся в коде.

- [ ] **Step 1: Failing-тесты:** `effective_status` для дат: до `ends_at` → `active`/`trial`, +10 дней → `grace`, +30 дней → `readonly`, +60 дней → `blocked`; `lifetime` всегда `active`; при `readonly` `POST` даёт 403 `subscription_readonly`, а `GET` 200; `blocked` блокирует вход; компания без модуля `fleet` получает 403 `module_disabled` на эндпоинтах `fleet`; `check_limit` срабатывает на границе.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** модели и сервисы; `create_company_with_defaults` создаёт подписку на `start` с `is_free_period=True`.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Режимы компании, тарифы, подписка и лимиты`.

### Task 6: Справочники

**Files:**
- Create: `backend/apps/core/handbooks/{models,defaults,api}.py`
- Test: `backend/apps/core/tests/test_handbooks.py`

**Interfaces:**
- Produces:
  - `Handbook(TenantModel: code, name, group)`, `HandbookValue(TenantModel: handbook, name, order, is_initial, is_final, is_active)`.
  - `defaults.DEFAULTS: dict[str, list[dict]]` с кодами: `order_status`, `consignment_status`, `trip_status`, `currency`, `client_type`, `carrier_type`, `packaging`, `loading_method`, `country`, `payment_delay_condition`, `transport_condition`.
  - `seed_handbooks(company: Company) -> None`, вызывается из `create_company_with_defaults`.
  - `GET /api/handbooks/?code=order_status`, CRUD значений (право `handbooks.*`).

- [ ] **Step 1: Failing-тесты:** после создания компании `order_status` содержит 7 значений в порядке из Global Constraints, ровно одно начальное; значение справочника, используемое записью, нельзя удалить, только деактивировать; значения компании A не видны компании B.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** модели, сидинг и API.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Справочники с набором по умолчанию`.

### Task 7: Нумерация

**Files:**
- Create: `backend/apps/core/numbering/{models,services,api}.py`
- Test: `backend/apps/core/tests/test_numbering.py`

**Interfaces:**
- Produces:
  - `NumberingRule(TenantModel: kind, template, digits, next_value)`; `kind` из `order | trip | consolidated_trip | invoice_out | invoice_in`.
  - `numbering.services.next_number(kind: str, **context: str | int) -> str`: блокирует строку правила (`select_for_update`), подставляет `{year}`, `{index}` (с ведущими нулями по `digits`), `{order}`, `{n}`, увеличивает счётчик.
  - `seed_numbering(company: Company) -> None` с шаблонами из Global Constraints.
  - API: список правил, изменение шаблона и ручная установка `next_value` (право `numbering.update`).

- [ ] **Step 1: Failing-тесты:** первый заказ получает `ORD-2026-00001`, второй `ORD-2026-00002`; `next_number("trip", order="ORD-2026-00001", n=2)` даёт `ORD-2026-00001-2`; `next_number("consolidated_trip")` даёт `C1`, затем `C2`; при двух параллельных потоках (`threading` + `transaction.atomic`) возвращаются два разных номера; ручная установка `next_value=100` даёт следующим `ORD-2026-00100`.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** сервис; для теста параллелизма использовать `pytest.mark.django_db(transaction=True)`.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Нумерация по шаблонам с безопасным счётчиком`.

### Task 8: Аудит и корзина

**Files:**
- Create: `backend/apps/core/audit/{models,signals,api}.py`, `backend/apps/core/trash.py`
- Test: `backend/apps/core/tests/test_audit_trash.py`

**Interfaces:**
- Consumes: `SoftDeleteModel`.
- Produces:
  - `AuditLog(TenantModel: user, action: create|update|delete|restore|login, object_type, object_id, changes: dict, created_at)`; `audit.log(action: str, obj: Model, user: User, changes: dict | None = None) -> None`.
  - `trash.register(model: type[SoftDeleteModel], code: str, permission: str) -> None`.
  - `GET /api/trash/` (все удалённые объекты компании, только по зарегистрированным типам), `POST /api/trash/{code}/{id}/restore/` (право `trash.update`).
  - Вход пользователя пишет запись `login`.

- [ ] **Step 1: Failing-тесты:** удаление и восстановление записи через API создают записи аудита; корзина показывает удалённое только своей компании; восстановление чужого объекта даёт 404.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** сервис и API; регистрация типов вызывается из `AppConfig.ready()` модулей (используется в Tasks 9–11).
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Журнал аудита и корзина`.

### Task 9: RLS в PostgreSQL

**Files:**
- Create: `backend/apps/core/migrations/0002_rls.py`, `backend/apps/core/rls.py`
- Modify: `tenancy.set_current_company` (выставляет `app.company_id` в сессии БД)
- Test: `backend/apps/core/tests/test_rls.py`

**Interfaces:**
- Produces: политика `tenant_isolation` с `USING (company_id = current_setting('app.company_id')::int)` на всех таблицах моделей `TenantModel`; помощник `rls.enable_for(model) -> None`, который вызывают миграции модулей; роль БД приложения без права обхода RLS (`FORCE ROW LEVEL SECURITY`).

- [ ] **Step 1: Failing-тест:** под ролью приложения прямой SQL `SELECT * FROM core_department` без `app.company_id` возвращает 0 строк, а с `set_config('app.company_id', A)` только строки компании A, даже при `Department.all_objects.all()`.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** миграцию и помощник; роль приложения создаётся в `docker-compose` и в CI-скрипте инициализации БД; `set_config(..., true)` вызывается внутри транзакции запроса (`ATOMIC_REQUESTS`).
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `RLS как вторая линия изоляции`.

### Task 10: Клиенты и перевозчики

**Files:**
- Create: `backend/apps/forwarding/{models,api,filters}.py`, `backend/apps/forwarding/apps.py`, `backend/apps/forwarding/tests/test_parties.py`

**Interfaces:**
- Consumes: `TenantModel`, `SoftDeleteModel`, `HandbookValue`, `permission_required`, `ModuleRequired("forwarding")`.
- Produces:
  - `Client(TenantModel, SoftDeleteModel: name, bin_iin, type FK HandbookValue, status active|inactive, credit_limit Decimal, notes)`, `Carrier(...: name, bin_iin, type, status, rating Decimal(2,1))`, `Contact(TenantModel: client null, carrier null, name, position, phone, email)`.
  - API `/api/clients/`, `/api/carriers/` (поиск по названию и БИН, фильтры по типу и статусу, поле `orders_count` у клиента).

- [ ] **Step 1: Failing-тесты:** создание клиента с БИН; поиск по части названия на кириллице; клиент компании A недоступен компании B по id (404); удаление уходит в корзину; рейтинг вне 0–5 отклоняется.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** модели, сериализаторы и viewset’ы; зарегистрировать типы в корзине.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Клиенты и перевозчики`.

### Task 11: Заказы и грузы

**Files:**
- Create: `backend/apps/forwarding/{orders,consignments}/{models,api,services}.py`, тесты в `backend/apps/forwarding/tests/test_orders.py`

**Interfaces:**
- Consumes: `next_number`, `Client`, `User`, `LegalEntity`, `HandbookValue`, `audit.log`.
- Produces:
  - `Order(number, client, client_ref, contract_number, contact, manager, forwarder null, extra_managers M2M, legal_entity, client_rate Decimal, currency, transport_condition, delivery_days, payment_delay_days, payment_delay_condition, comment, status, completed_at null)`, `OrderStatusHistory(order, from_status, to_status, user, created_at)`.
  - `Consignment(order, name, weight_kg, volume_m3, pallets, packaging, status)`, `ConsignmentPoint(consignment, kind: load|unload, window_from, window_to null, country, city, street, method, contact, postal_code, lat null, lng null, note)`.
  - `orders.services.create_order(data: dict, user: User) -> Order` (генерирует номер, начальный статус, пишет аудит), `change_status(order: Order, status: HandbookValue, user: User) -> Order` (пишет историю; при конечном статусе `Завершён` ставит `completed_at`).
  - API `/api/orders/`, `/api/orders/{id}/status/`, `/api/consignments/`; поле `route` в ответе (`"Шымкент → Алматы"` из точек первого груза); `has_carrier` из рейсов.

- [ ] **Step 1: Failing-тесты:** создание заказа с грузом и двумя точками возвращает `ORD-2026-00001`, статус «Новый» и `route`; смена статуса пишет историю и аудит; `Завершён` ставит `completed_at`; заказ без грузов создаётся и отдаётся без ошибки; чужой заказ по id даёт 404; менеджер без права `orders.update` не меняет статус (403).
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** модели, сервисы и сериализаторы с вложенным созданием груза и точек в одной транзакции.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Заказы, грузы и история статусов`.

### Task 12: Рейсы и консолидация

**Files:**
- Create: `backend/apps/forwarding/trips/{models,api,services}.py`, `backend/apps/forwarding/tests/test_trips.py`

**Interfaces:**
- Consumes: `Consignment`, `Carrier`, `next_number`.
- Produces:
  - `Trip(number, carrier null, vehicle_plate, driver_name, price Decimal, currency, status, is_consolidated)` и связь `Trip.consignments` (M2M). Поля `vehicle_plate` и `driver_name` временные: на этапе 4 заменяются ссылками на собственный автопарк.
  - `trips.services.create_trip(consignment_ids: list[int], carrier_id: int | None, data: dict, user: User) -> Trip`: все грузы одной компании; если грузы из одного заказа, номер `{order}-{n}`, иначе `C{index}` и `is_consolidated=True`.
  - `trips.services.reassign(trip: Trip, consignment_ids: list[int]) -> Trip`.
  - API `/api/trips/`, `/api/consignments/?without_trip=1` (очередь распределения).

- [ ] **Step 1: Failing-тесты:** рейс на груз заказа получает номер `ORD-…-1`, второй рейс того же заказа `-2`; рейс на грузы двух заказов получает `C1` и `is_consolidated=True`; груз чужой компании в списке даёт 400; грузы без рейса попадают в очередь; после создания рейса у заказа `has_carrier=True`.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** сервисы в транзакции.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Рейсы и консолидация грузов`.

### Task 13: Строки заказа, прибыль и дашборд

**Files:**
- Create: `backend/apps/forwarding/finance_lines/{models,services,api}.py`, `backend/apps/forwarding/dashboard.py`, `backend/apps/forwarding/tests/test_dashboard.py`

**Interfaces:**
- Produces:
  - `OrderService(TenantModel: order, title, category null, income Decimal, expense Decimal, date)`.
  - `order_totals(order: Order) -> dict` с ключами `revenue`, `cost`, `profit` (`Decimal`) и `margin_pct` (`Decimal | None`, `None` при `revenue == 0`).
  - `GET /api/dashboard/summary/` → `active_orders`, `completed_orders`, `clients`, `carriers`, `orders_by_status: [{status, count}]`, `month_profit`, `month_margin_pct`, `unassigned_orders`; месяц считается в часовом поясе компании; завершённые считаются с даты «начала учёта» из настроек компании (поле `Company.accounting_start`, по умолчанию пусто).

- [ ] **Step 1: Failing-тесты:** строки дохода 1 000 000 и расхода 770 000 дают прибыль 230 000 и маржу `23.00`; при нулевой выручке `margin_pct is None`; дашборд пустой компании возвращает нули без ошибок; заказы без перевозчика считаются в `unassigned_orders`; дашборд компании A не включает данные B.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** сервис агрегации через ORM (`Sum`, `Coalesce`).
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Строки заказа, прибыль и сводка дашборда`.

### Task 14: Списки, канбан, Excel, оформление

**Files:**
- Modify: `forwarding/orders/api.py`; Create: `backend/apps/forwarding/orders/{export,board}.py`, `backend/apps/core/branding.py`, `backend/apps/forwarding/tests/test_order_views.py`

**Interfaces:**
- Produces:
  - Фильтры `/api/orders/`: `q` (номер, груз, клиент), `status` (несколько), `client`, `carrier`, `loading_from`, `loading_to`, `created_from`, `created_to`, `completed_from`, `completed_to`, `unassigned`.
  - `GET /api/orders/board/` → `[{status, count, orders:[{id, number, client, route, carrier, rate, loading_at}]}]`.
  - `GET /api/orders/export/` → `.xlsx` с теми же фильтрами (`openpyxl`).
  - `CompanyBranding(OneToOne Company: app_name, logo, primary_color, theme)`; `GET/PATCH /api/company/branding/` (право `company.update`), публичный `GET /api/branding/?host=` для экрана входа.

- [ ] **Step 1: Failing-тесты:** фильтр по двум статусам; поиск «Консервы» находит заказ по грузу; канбан возвращает колонки в порядке справочника, включая пустые; Excel открывается `openpyxl.load_workbook` и содержит строку на каждый заказ выборки; смена цвета оформления сохраняется и не затрагивает другую компанию.
- [ ] **Step 2: Запустить**, ожидать FAIL.
- [ ] **Step 3: Реализовать** фильтры, выгрузку и оформление.
- [ ] **Step 4: Запустить**, ожидать PASS.
- [ ] **Step 5: Commit** `Фильтры заказов, канбан, Excel и оформление компании`.

### Task 15: Фронтенд: каркас, вход, меню

**Files:**
- Create: `web/` (Vite React TS), `web/src/{main.tsx,app/router.tsx,shared/api/client.ts,shared/i18n/{ru,kk}.json,shared/theme.ts,shared/auth/*,layout/Sidebar.tsx}`, `web/vitest.config.ts`
- Test: `web/src/shared/auth/auth.test.tsx`, `web/src/layout/Sidebar.test.tsx`

**Interfaces:**
- Consumes: `/api/auth/login/`, `/api/auth/switch-company/`, `/api/company/branding/`, права и режимы из ответа `GET /api/session/` (добавить: `{user, company, modules, permissions, subscription_status}`).
- Produces: `api.get/post/patch/delete` (единственный клиент, обновление токена), `useSession()`, `applyBranding(b: Branding) -> void` (CSS-переменные `--brand-500` и др.), `Sidebar` показывает разделы по `modules` и `permissions`.

- [ ] **Step 1: Failing-тесты:** Sidebar скрывает «Автопарк» без модуля `fleet` и «Пользователи» без права `users.view`; `applyBranding({primary_color:"#2563eb"})` выставляет `--brand-500`; при ответе `subscription_readonly` показывается баннер и кнопки записи отключены.
- [ ] **Step 2: Запустить** `cd web && npm test`, ожидать FAIL.
- [ ] **Step 3: Реализовать** каркас, маршруты, вход, i18n (ru, kk), тему; в `core/api` добавить `GET /api/session/`.
- [ ] **Step 4: Запустить** `npm test && npm run typecheck && npm run lint && npm run build`, ожидать PASS.
- [ ] **Step 5: Commit** `Фронтенд: каркас, вход, меню по правам и режимам`.

### Task 16: Фронтенд: экспедиторские страницы

**Files:**
- Create: `web/src/features/{dashboard,clients,carriers,orders,consignments,trips,trash,settings}/*`
- Test: рядом с каждой страницей `*.test.tsx`

**Interfaces:**
- Consumes: API Tasks 6–14.
- Produces: страницы Дашборд, Клиенты, Перевозчики, Заказы (список, канбан, выгрузка, форма «Новый заказ» из четырёх блоков), Грузы (очередь распределения, создание рейса), Рейсы, Корзина, Настройки (компания, оформление, пользователи, роли и права, справочники, нумерация).

- [ ] **Step 1: Failing-тесты:** форма заказа не отправляется без клиента, груза и обеих точек и показывает ошибки; пустой список показывает «пустое состояние» с кнопкой создания; канбан показывает все колонки и «без перевозчика»; заказы без маржи показывают «—», а не `NaN` или `Infinity`.
- [ ] **Step 2: Запустить** `npm test`, ожидать FAIL.
- [ ] **Step 3: Реализовать** страницы на TanStack Query; плотная компактная таблица; все строки через i18n.
- [ ] **Step 4: Запустить** `npm test && npm run typecheck && npm run lint && npm run build`, ожидать PASS.
- [ ] **Step 5: Commit** `Фронтенд: страницы экспедиторского контура`.

### Task 17: Деплой на hoster.kz

**Files:**
- Create: `deploy/{Dockerfile.backend,Dockerfile.web,docker-compose.prod.yml,nginx.conf,backup.sh,restore.sh}`, `.github/workflows/deploy.yml`, `docs/ops/RUNBOOK.md`

**Interfaces:**
- Produces: образы backend/web, compose с `nginx, backend, worker, beat, postgres, redis, minio`; `backup.sh` ежедневный дамп БД и файлов на отдельное казахстанское хранилище; `restore.sh <архив>`; деплой на `staging` из ветки `main`, на `production` по тегу.

- [ ] **Step 1: Failing-проверка:** скрипт `deploy/smoke.sh` обращается к `/api/health/` и главной странице и завершается ненулевым кодом, пока стек не поднят.
- [ ] **Step 2: Запустить** `./deploy/smoke.sh`, ожидать FAIL.
- [ ] **Step 3: Реализовать** образы, compose, Nginx (определение компании по `Host`), бэкап и восстановление; Sentry с `send_default_pii=False`.
- [ ] **Step 4: Запустить** локально `docker compose -f deploy/docker-compose.prod.yml up -d && ./deploy/smoke.sh`, ожидать PASS; выполнить `backup.sh` и `restore.sh` на тестовых данных и сверить число записей.
- [ ] **Step 5: Commit** `Деплой, бэкапы и регламент`.

---

## Самопроверка плана

- **Покрытие спецификации (этапы 1–2):** компании и режимы (Tasks 2, 5), пользователи и вход (3), роли и права (4), справочники (6), нумерация (7), аудит и корзина (8), RLS (9), тарифы, лицензия, подписка и лимиты (5), оформление первого уровня (14, 15), клиенты и перевозчики (10), заказы, грузы, рейсы, консолидация (11, 12), строки, прибыль и дашборд (13), канбан, Excel, фильтры (14), интерфейс (15, 16), инфраструктура, CI, бэкапы, хостинг (1, 17). Админка платформы с ручными счетами и белая метка второго уровня отнесены к этапу 5 спецификации.
- **Решения плана, которых не было в спецификации:** сроки `grace` 14 дней и `readonly` 30 дней; временные текстовые поля машины и водителя в рейсе до этапа 4; `Company.accounting_start`.
- **Согласованность имён:** `next_number`, `create_company_with_defaults`, `set_current_company`, `permission_required`, `check_limit` и `effective_status` используются везде с одинаковыми сигнатурами.
