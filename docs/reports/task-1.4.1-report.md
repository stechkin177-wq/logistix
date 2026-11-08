# Отчёт 1.4.1: модели, миграции M1-M6, права, RLS под logistix_app

Статус: **DONE**. Бизнес-логика сервисов не добавлялась. Не пушилось, в main не сливалось, демо и демо-БД не затрагивались.

## 1. Изменённые файлы
- core: `handbooks/defaults.py`, `handbooks/system_codes.py`, `permissions_catalog.py`, миграции `0013_expense_category_handbook`, `0014_finance_architecture_permissions`.
- finance: `models.py`, `apps.py`, `initial_settings.py` (новый), миграции `0004`-`0007`, `rates.py`, `api/rates.py`, `operations.py` (только фильтр `quote_currency IS NULL`, поведение прежнее).
- scripts: `verify_upgrade_task_1_4_1.py`, `verify_rls_task_1_4_1.py`, `rls_battery_task_1_4_1.py`, `task_1_4_1_common.py`; в `verify_upgrade_task_1_1.py` поправлено исходное состояние (finance до 0003, без обработчика/категорий), иначе скрипт 1.1 ломался.
- тесты: `core/tests/test_finance_architecture_core.py`, `test_upgrade_script_1_4_1.py`, `test_rls_script_1_4_1.py`; `finance/tests/test_ledger_models.py`, `test_financial_settings_setup.py`; правки счётчиков в `test_roles.py`, `test_handbooks.py`, `test_documents_core.py`, `test_trip_status_codes.py`.
- web: `features/settings/roles/catalog.ts`, `ExtraPermissions.test.tsx`, `RolesPage.test.tsx`, `shared/i18n/ru.json`, `kk.json`, `test/permissions.ts`.

## 2. Модели
CompanyFinancialSettings, FinancialPeriod, FinancialPeriodEvent, Income, IncomeTrip, Expense, ExpenseAllocation, ExpenseInvoiceAllocation, FinanceMigrationRun, FinanceMigrationIssue - поля и ограничения по брифу (все TenantModel + RLS). Общий абстрактный `FxSnapshot` для FX-полей Income/Expense. Дополнительно (не из брифа): DB-check допустимых значений для `engine`, `FinancialPeriod.status`, `FinancialPeriodEvent.action`. Валидация валюты/статуса/НДС - `CompanyFinancialSettings.clean()`. `allow_backdating` по умолчанию True. related_name: Order.incomes, Trip.expenses, Carrier.expenses, Expense.allocations/invoice_allocations, OrderService.finance_income/finance_allocation. InvoiceItem.income, ExchangeRate.quote_currency + уникальности `exchangerate_kzt_uniq`, `exchangerate_pair_uniq`, check `exchangerate_currency_ne_quote`.

## 3. Миграции
| Шаг | Файл | Обратимость / влияние на данные |
|---|---|---|
| M1 | finance.0004 | схема + RLS (inline SQL, без импортов apps.*); откат удаляет таблицы |
| M2 | core.0013 | засев expense_category существующим компаниям, идемпотентно, существующее не трогает; откат noop |
| M3 | finance.0005 | 7 таблиц + RLS; откат удаляет таблицы (они новые) |
| M4 | finance.0006 | preflight + пересборка уникальности; курсы не меняются. Откат блокируется RuntimeError, если есть курсы пар или позиции счетов с income (не удаляем новые данные) |
| M5 | finance.0007 | строка настроек на компанию (legacy, backdating=True, ...); completed_status только при ровно одном активном COMPLETED, base_currency только при ровно одном KZT; идемпотентно; откат noop |
| M6 | core.0014 | права по матрице (Админ 5, Бухгалтер 3), только добавляет; откат noop |

Preflight M4 (по каждой компании с set_config и сбросом в finally): дубликаты (компания, валюта, дата) и записи курса для KZT. Конфликт - остановка со списком, ничего не удаляется. Проверка на искусственном конфликте в отдельной БД: остановлено, курсы и схема не тронуты.
Для новых компаний: обработчик `company_created` в finance (`initial_settings.py`), core finance не импортирует (тест по AST).

## 4. Права
Новые коды в отдельном списке `FINANCE_ARCHITECTURE_PERMISSIONS`; Администратор - все пять, Бухгалтер - close_period, adjust_closed, backdate, остальные - ноль. Всего прав 60. Назначаются пользовательским ролям через /api/roles/ (тест), «выше своих» не выдать (тест). Frontend: пять чекбоксов в «Особых правах», подписи ru/kk.

## 5. Тесты и РЕАЛЬНЫЕ результаты
Запускалось:
- `pytest apps/finance apps/core` (целиком эти два пакета, включая обёртки скриптов): 829 passed, 2 failed, 1 error - это были устаревшие счётчики/сид (55 прав, FK на completed_status при ручном удалении статусов, скрипт 1.1). Исправлено, перепрогнаны эти файлы: 35 passed. Полный повторный прогон двух пакетов после правок не делался.
- Новые тесты: test_ledger_models 28, test_financial_settings_setup 16, test_finance_architecture_core 16 - все passed.
- `scripts/verify_upgrade_task_1_4_1.py`: OK 1 (БД с данными, 5 сценариев компаний, курсы неизменны по контрольной сумме, идемпотентность M2/M5/M6, откат M6..M1 и повтор), OK 2 (preflight), OK 3 (чистая БД с нуля + makemigrations --check).
- `scripts/verify_rls_task_1_4_1.py` (реальная роль logistix_app, создана настоящим deploy/db-init.sql, не суперпользователь, без BYPASSRLS): шаги base, M1, M2, M3, M4, M5, M6 - все OK (примерно 290-500 проверок на шаг: fail closed без контекста, свои строки, чужая компания не читает/не меняет/не удаляет/не вставляет/не переносит, ROLLBACK и savepoint, повторное использование соединения, FORCE для владельца через пробу). Мутационная проверка: при замене FORCE на NO FORCE скрипт падает. `tables_missing_rls() == []` после M6.
- ruff check, ruff format --check, makemigrations --check: чисто.
- web: eslint, `tsc -b --noEmit` чисто; vitest по каталогу ролей 20 passed. (До смены порядка также был полный vitest 419 passed и build - успешно.)
НЕ запускалось: полный pytest (прерван по решению заказчика о порядке проверок), повторные полные прогоны, CI.

## 6. Риски и оговорки
- В `rates.py`, `api/rates.py`, `operations.py` добавлен фильтр `quote_currency IS NULL`, чтобы будущие парные курсы не попали в курсы к тенге (текущее поведение неизменно).
- Preflight M4 считает конфликтом также запись курса для KZT (на текущем API такие не создаются).
- base_currency при нескольких/нулевых KZT остаётся NULL.
- Скрипты RLS/обновления меняют на локальном кластере роль logistix_app (LOGIN, пароль разработки) через db-init.sql; демо-БД не затрагивается.
- Откат M1/M3 удаляет новые таблицы (штатно для структуры; M4 защищён).
- Тесты скриптов длятся ~40 с каждый.
