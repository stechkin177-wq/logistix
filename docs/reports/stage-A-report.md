# Отчёт: этап 1.5-A «Модульная архитектура компании» (A1-A7)

Ветка `claude/epic-bohr-380x91`, база 4c19160. Не пушилось, в `main` не сливалось, демо/демо-база/production не затрагивались, engine реальных компаний не переключался, `Company.modules` и старые API-алиасы не удалялись. Статус: **DONE** (с оговорками ниже).

## Коммиты

| Блок | Хеш | Содержание |
|---|---|---|
| A1 | 0498c3f | `Module`, `ActivityProfile` (платформенные, без RLS), посев core.0015, код-реестр, проверка циклов |
| A2 | af877db | `CompanyModule` (RLS), core.0016/0017, billing.0003, проекция `Company.modules`, чтение прав из `CompanyModule` |
| A3 | ca3ce95 | `ModuleRequired` = тариф И `CompanyModule`; finance/documents API на свои модули; frontend меню/маршруты |
| A4 | fae79cd | `enable_module`/`disable_module`, зависимости, cascade, защита finance при shadow/new |
| A5 | 3a68ae1 | право `company.manage_modules`, core.0018, аудит, frontend каталог прав и подписи ru/kk |
| A6 | 0b0d594 | API модулей/профилей, страница «Модули компании» |
| A7 | a75c2d5 | `subject_type`/`subject_id`, documents.0003/0004, реестр поставщиков, встроенные поставщики, выдача по субъекту |
| RLS | 9775a4e | `verify_rls_stage_A.py` + батарея + обёртка-тест |

Миграции: core 0015 (каталог + посев), 0016 (CompanyModule + `EnableRLS`), 0017 (перенос данных), 0018 (право Администратору); billing 0003 (тарифы); documents 0003 (поля + индекс), 0004 (заполнение субъекта). Все аддитивные, обратимые, без импорта кода приложения (константы внутри), идемпотентные.

## Что запускалось

- Скрипт `scripts/verify_rls_stage_A.py` (обёртка `apps/core/tests/test_rls_script_stage_a.py`): временная БД, роль `logistix_app` (NOSUPERUSER NOBYPASSRLS) из `deploy/db-init.sql`, две компании с данными (A: forwarding; B: forwarding+fleet; клиент, заказ, рейс, счёт, документы всех 7 видов + письмо без заказа). Шаги: core 0015 -> 0016 -> 0017 -> billing 0003 -> core 0018 -> documents 0003 -> 0004; после КАЖДОГО шага батарея под `logistix_app` (fail closed, чтение/запись своих, чужая компания не видит/не меняет/не удаляет/не вставляет/не переносит, сброс контекста после ROLLBACK/savepoint/переиспользования соединения, FORCE RLS у владельца). Проверки данных: `CompanyModule` создан, finance и documents включены у forwarding-компаний, `core` не хранится, проекция = `CompanyModule`, прежний состав и порядок `Company.modules` сохранён, тарифы дополнены, субъекты документов заполнены, прежние поля документов не изменены. Откат всех шагов (documents 0004 -> 0002, billing -> 0002, core -> 0014) без потерь (Company.modules и тарифы возвращаются к исходным), повторное применение, мутационная проверка (без FORCE RLS батарея падает), `tables_missing_rls() == []`, `makemigrations --check`. Итог: 13 шагов, 1616 проверок, код 0.
- Тесты A1-A7 (новые): `test_module_catalog`, `test_company_modules`, `test_module_rules`, `test_module_access_matrix` (тариф x компания x право на реальных эндпоинтах forwarding/finance/documents), `test_module_permission`, `test_module_api`, `documents/tests/test_subject_providers`, `test_rls_script_stage_a`.
- Совместимость (итоговый прогон затронутых приложений): `pytest apps/billing apps/core apps/documents apps/finance apps/forwarding` - результат в разделе «Итоговый прогон» ниже.
- Frontend: `vitest` (весь набор, 459 тестов, быстрый), `tsc -p tsconfig.app.json --noEmit`, `eslint src` - без ошибок. Backend: `ruff check`, `ruff format --check`, `makemigrations --check`.

## Чего НЕ запускалось

- Полный pytest всего проекта (запускались только приложения billing, core, documents, finance, forwarding - они и есть весь backend, но без CI и без повторных прогонов).
- `npm run build`, CI на GitHub.
- Проверка на реальных/демо-данных и миграции на демо-базе (запрещено).
- Вложения (`Attachment`) не создавались (этап 3 ТЗ), поставщики документов для fleet/drivers не добавлялись (этап 2).

## Итоговый прогон

`pytest apps/billing apps/core apps/documents apps/finance apps/forwarding`: **2083 passed, 0 failed** (17 мин), включая все прежние тесты finance/documents/forwarding/core (кроме обновлённых счётчиков и составов, перечисленных ниже) и скрипты RLS/апгрейда прежних подзадач. Замечание: полный vitest (459 тестов, ~35 с) тоже был запущен целиком, а не только затронутые файлы.

## Интерпретации и решения без явного указания в ТЗ

1. **Новые компании.** `create_company_with_defaults`/`bootstrap_company` с `forwarding` дополнительно включают `finance` и `documents` (как миграция для существующих; иначе новые компании теряли бы финансы и документы и ломались бы все тесты через `make_company`). Требования `requires` при создании проверяются (`ValueError`). Прямое `Company.objects.create(...)` строк `CompanyModule` не создаёт (поле-значение по умолчанию `["forwarding"]` не менял).
2. **Проекция.** Миграция 0017 приводит `Company.modules` к включённым модулям: прежний состав и порядок сохраняются в начале, `finance`/`documents` добавляются в конец (то есть у forwarding-компаний `Company.modules` стал шире, чем был). Порядок «эффективных» модулей в `/api/session/` = порядок создания строк `CompanyModule`; формат ответа не менялся.
3. **Статусы каталога:** `core`, `documents`, `forwarding`, `finance`, `fleet` - `available`; остальные (drivers, driver_app, gps, ocr, notifications, analytics) - `beta`. Включение `retired` запрещено (`module_retired`, 400).
4. **API.** `enable_module` без параметра `cascade` (каскад включения требований не вводился - это решение о бизнес-логике); `cascade` есть у `disable_module`. `reason` на API необязателен (экран требует причину при отключении). Повторное включение/отключение уже включённого/отключённого - без изменений и без записи в аудит (защита от двойной отправки). Коды: 400 `module_unknown|module_core|module_retired`, 409 `module_not_in_plan|module_requires|module_has_dependents|module_protected`.
5. **Аудит.** Используется действие `update`/`create` на объекте `core.companymodule` с `changes = {module_code, enabled: [старое, новое], reason}`; пользователь и IP пишет сервис аудита.
6. **Профили.** `apply-profile` включает модули профиля в порядке зависимостей; недоступные по тарифу и модули с невыполнимыми `requires` пропускает и перечисляет (`skipped[].error_code`); `replace=true` отключает остальные (каскадно, под защитой finance), при отказе откатывается всё. Профиль при регистрации компании не предлагался (в ТЗ A6 - настройки); коды профилей: `forwarder`, `carrier`, `forwarder_carrier`.
7. **Документы.** Встроенные виды зарегистрированы двумя поставщиками: `forwarding` (договор, заявка, заказ перевозчику, CMR, письмо) и `finance` (акт, счёт на оплату); выдача прежнего вида требует модуль поставщика (при всех включённых модулях поведение прежнее). К интерфейсу `DocumentProvider` добавлен `load_subject(subject_type, subject_id)` (ядро не может загружать модели других модулей). Виды новых поставщиков должны входить в `documents.models.KINDS` (CHECK-ограничения БД на виды не менялись) - расширение списка видов для fleet/drivers потребует миграции в этапе 2. Новый эндпоинт `GET /api/documents/kinds/` (доступные виды); `capabilities` не менялся (тест закрепляет его состав). Выдача по субъекту: `POST /api/documents/issued/` с `subject_type` + `subject_id` (взамен client/order/trip/invoice).
8. **Чтение модулей в запросе.** Чтобы не добавлять запрос в каждый вызов (тесты фиксируют число запросов), включённые модули читаются подзапросом `ArraySubquery` в том же запросе аутентификации (`membership.enabled_module_codes`).
9. **Защита finance.** Регистрируется приложением finance (`register_disable_guard`), ядро не импортирует модели finance. Фоновые хуки движка от видимости модуля не зависят (их код не менялся).

## Изменения существующих тестов и скриптов (честное обновление)

- Счётчик прав 60 -> 61 (`test_roles`, `test_documents_core`, `test_finance_architecture_core`; в последнем сравнение префикса прав Администратора уточнено); `RolesPage.test.tsx` 60 -> 61 флажков.
- `test_subscription` (состав модулей тарифов теперь с finance и documents), `test_session`, `test_fixtures`, `test_bootstrap_company` (состав `Company.modules` у новых forwarding-компаний), `nav.test.ts`, `Sidebar.test.tsx`, `test/fixtures.ts` (сессия по умолчанию с finance и documents).
- Скрипты старых состояний схемы (`verify_rls_task_1_4_1`, `verify_upgrade_task_1_1`, `verify_upgrade_task_1_4_1`) сидят компании до появления `CompanyModule`, поэтому в их SEED подставлена прежняя запись модулей (shim); батарея 1.4.1 знает о таблице `core_companymodule` (`LATER_TABLES`).

## Оговорки и известные ограничения

- В платформенной админ-панели управления каталогом/профилями нет (только миграции и данные); при необходимости - отдельная задача.
- `Company.modules` остаётся и обновляется как проекция; удаление - отдельным решением.
- `fleet` остаётся доступным модулем каталога (как и раньше был флагом); функционала у остальных `beta`-модулей пока нет - их включение только меняет конфигурацию.
- Встроенный поставщик letter привязан к forwarding: при выключенном forwarding «письмо» с субъектом заказа/без субъекта через старый путь недоступно; письмо по субъекту drivers.driver возможно только если зарегистрирован поставщик drivers.
- Порядок `CompanyModule` для отключённых и повторно включённых модулей сохраняет исходную строку (id), поэтому порядок в `/api/session/` не «прыгает».
