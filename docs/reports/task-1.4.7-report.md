# Отчёт 1.4.7: Shadow-запись

Статус: **DONE**. Миграций нет. Не пушилось. Engine ни одной компании не менялся.

## Файлы
Новые: `finance/shadow.py`, `finance/migration.py` (общий классификатор/перенос, нужен и для 1.4.8; см. отчёт 1.4.8), `finance/tests/test_shadow.py` (11 тестов). Изменены: `finance/hooks.py` (ветка shadow, `after_line_saved`, `before_line_delete`, `after_line_deleted`), `forwarding/finance_lines/api.py` (хуки create/update/delete строки), `finance/trip_expense.py`, `finance/invoices.py` (`issue` -> зеркало связей), `finance/expenses.py` (`_write_allocations` обновляет доли по разности и сохраняет legacy_line неизменных долей).

## Поведение
- Хуки работают только при engine == 'shadow'; для 'legacy' и 'new' зеркало не пишется (тест).
- Точки: создание заказа и смена client_rate (базовая строка), создание/изменение/удаление строки через /api/order-lines/, `create_trip_expense`, `issue` счёта (связи с перенесёнными строками); отмена счёта освобождает связи штатным `release_on_cancel` (1.4.6). Смена статуса рейса ничего не пишет.
- Зеркало = `migrate_order(order, overwrite=True)` / `migrate_invoice_links` внутри вложенного `transaction.atomic()`. Ошибка: savepoint откатывается целиком (частично записанное не остаётся), основная операция завершается, после отката создаётся `FinanceMigrationIssue(shadow_error, error)` с операцией, объектом и текстом ошибки (класс и сообщение, без секретов).
- Удаление строки: до удаления Income -> void (`legacy_line_deleted`, legacy_line=NULL), доля расхода удаляется с аудитом, у зеркального расхода без долей - void, иначе сумма пересчитывается (группа рейса помечается migrated_mismatch); ProtectedError не возникает. После удаления остальные строки группы пересчитываются.
- Старые данные (OrderService, счета, платежи, rate_to_kzt) не меняются (тест).

## Тесты (реальные результаты)
- `pytest apps/finance/tests/test_shadow.py` (+ test_expenses): 37 passed: создание заказа и смена client_rate, строка create/update/delete и обнуление, сборный рейс (один расход, 3 доли, повтор без дублей, удаление строки пересчитывает), issue/cancel счетов (исходящий и входящий), legacy/new без зеркала, принудительное исключение (операция выполнена, зеркала нет, Issue есть, частичная запись откатилась), параллельные зеркала без дублей, set_allocations сохраняет legacy_line.
- `pytest test_order_lines, test_trip_expense, test_invoices_service, test_invoices_api`: 69 passed. ruff, `makemigrations --check`: чисто.
- НЕ запускалось: полный pytest, frontend, CI; RLS-скрипт П3 - в конце пакета.

## Риски
- Вызов зеркала добавляет 1-2 запроса (engine) на каждую операцию строки/счёта даже в legacy.
- Зеркало перезаписывает (overwrite) совпадающие по legacy_line записи; правки новых записей вручную в shadow будут затёрты следующим зеркалом.
