# Отчёт 1.4.3: закрытые периоды, обратное датирование, сервис настроек

Статус: **DONE**. Миграций нет. Не пушилось.

## Изменённые файлы
- Новые: `backend/apps/finance/periods.py`, `settings_service.py`, `tests/test_periods.py` (33 теста), `backend/scripts/verify_rls_task_1_4_3.py`, `backend/apps/core/tests/test_rls_script_1_4_3.py`.
- Изменены: `finance/payments.py`, `invoices.py`, `trip_expense.py`, `api/invoices.py`, `api/payments.py`, `api/trips.py`, `forwarding/finance_lines/api.py`.

## Сервисы
- `close_period` (только полностью прошедший месяц по часовому поясу компании, иначе 409 `period_not_finished`; идемпотентно, блокировка строки, событие + аудит), `reopen_period` (причина обязательна, только из closed, период остаётся, история событий копится; контекст запроса не подменяется - чужой период не найдётся), `is_period_closed`, `assert_period_open` (409 `period_closed` / 400 `period_reason_required` / True = допущена корректировка), `assert_backdating_ok` (409 `backdating_forbidden`, дата сравнивается с «сегодня» компании; finance.adjust_closed правило не отменяет), `check_user_date` (обе проверки независимо), `check_system_date` (только период).
- `update_settings`: разрешены allow_backdating, default_vat_rate, fiscal_year_start_month, expense_creation_mode, sync_carrier_price, completed_status (значение trip_status своей компании, активное; очистка запрещена при engine=new); engine/cutover_date/income_recognition/accounting_method/base_currency - `setting_forbidden`; блокировка строки, один аудит со старым/новым.

## Защита в существующих операциях (при любом engine)
Оплата (создание: период + обратное датирование; удаление: период), выставление счёта и отмена (по дате выставления), строки заказа /api/order-lines/ (создание, изменение - старая и новая дата, удаление), расход по рейсу. API берёт права из `request.membership.role.permissions` и опциональное `adjust_reason` из тела. Корректировка пишется в аудит ключом `closed_period_adjustment` {reason, old, new}. Обратное датирование - только для дат, введённых пользователем (оплата, дата строки; не при правке суммы без смены даты). У компаний без закрытых периодов и с allow_backdating=True поведение прежнее.

## Права
Без изменений матрицы (1.4.1). Админ имеет adjust_closed/backdate; пользовательские роли получают их через /api/roles/.

## Тесты (реальные результаты)
- `pytest apps/finance apps/core apps/forwarding` одним прогоном: **1328 passed**.
- `test_periods.py` 33 passed: закрытие/повтор/текущий и будущий месяц/часовой пояс, переоткрытие с причиной и без, история, уникальность, изоляция, каждая защищённая операция (409 без права, 400 без причины, успех + аудит; открытый месяц как прежде), обратное датирование (сегодня/будущее/вчера, backdate, один adjust_closed, allow_backdating=True, граница полуночи в Алматы), update_settings (запрещённые поля, чужой/не тот справочник/неактивный статус, аудит, изоляция).
- `scripts/verify_rls_task_1_4_3.py` (реальная роль logistix_app, db-init.sql, все миграции): OK, 18 проверок (закрытие, настройки, смена базовой валюты, чужая компания не видит/не меняет/не переоткрывает, откат транзакции, сброс контекста). Обёртка-тест в core/tests.
- ruff check/format, `makemigrations --check`: чисто.
- НЕ запускалось: полный pytest (apps/billing, apps/documents и др.), frontend (vitest/lint/build), CI, повтор RLS-скриптов 1.4.1/upgrade (миграций нет).

## Риски и оговорки
- `adjust_reason` читается из тела любого запроса (в т.ч. DELETE с телом); без UI/документации API (1.4.12).
- Выставление счёта проверяет только период (дата — системная «сегодня» или переданная сервисом), обратное датирование там не применяется (по ТЗ только оплата и строки).
- Расход по рейсу проверяет период по «сегодня» компании; закрыть текущий месяц штатно нельзя, проверка защитная.
- Проверка периода для удаления/изменения использует сохранённую дату записи, а не дату создания.
