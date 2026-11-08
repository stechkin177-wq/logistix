# Отчёт 1.4.9: reconcile_finance

Статус: **DONE**. Миграций нет. Не пушилось. Данные не меняются (пишутся только Run и Issues reconcile_diff).

## Файлы
Новые: `finance/reports_new.py` (`order_totals_new`, `month_totals_new`, `operations_by_currency_new` - пригодятся для 1.4.11), `finance/reconcile.py`, `finance/management/commands/reconcile_finance.py`, `finance/tests/test_reconcile.py` (15 тестов), `backend/scripts/verify_rls_task_1_4_9.py`, `core/tests/test_rls_script_1_4_9.py`. Правки: `finance/migration.py` (`detach_line` в транзакции), тест `test_income.py` (shadow-зеркало базовой строки теперь учтено).

## Реализация
`reconcile_finance --company ID [--month YYYY-MM]` -> FinanceMigrationRun(kind=reconcile). Проверки: (1-2) суммы доходов и расходов по (валюта, месяц) в ИСХОДНОЙ валюте плюс построчно; (3) неперенесённые строки без проблемы; (4) открытые error-проблемы ambiguous_trip_expense / shadow_error / migrate_error - необъяснённые; (5) прибыль и маржа каждого заказа (старый `order_totals` против нового); (6) прибыль месяца (дашборд `_month_finance`) и журнал операций (`operations.summary`) против новых; (7) связи счетов, «сироты» (позиции без line) отдельным info-списком; (8) Σ долей (<= amount, при полном распределении ==), повторяющиеся срезы; (9) дубли legacy_line, активных расходов перевозчика на рейс, freight на заказ, ключей групп; (10) события без источника; (11) legacy_missing отдельным info-списком, суммы НЕ исключаются. Статус success только без необъяснённых расхождений; иначе needs_review. Строки с РУЧНО разрешённой проблемой считаются объяснёнными: исключаются из старой стороны и перечисляются. Расхождения оформляются Issues reconcile_diff (без дублей); не воспроизведённые повторной сверкой закрываются автоматически. Печатается читаемый отчёт.

## Тесты (реальные результаты)
- `pytest apps/finance/tests/test_reconcile.py`: 15 passed: согласованная БД - success и данные не менялись; изменённая сумма строки ловится в п.1/5/6 (дашборд и журнал); изменённый расход; потерянная связь счёта (доход и расход); дубли срезов и Σ долей; события без источника; неперенесённая строка; спорные строки блокируют success, после ручного разрешения - success; legacy_missing в списке и в суммах; мультивалюта и фильтр месяца; повторная сверка без дублей Issue и автозакрытие; изоляция; `reports_new` == старые расчёты; команда.
- Итог пакета одним прогоном `pytest apps/finance apps/forwarding apps/core/tests/test_rls_script_1_4_9.py apps/core/tests/test_rls_script_1_4_6.py`: 755 passed, 1 failed (test_income: устаревшее ожидание про shadow); исправлено, `test_income.py` повторно: 26 passed. Полный повтор пакета после исправления теста не делался.
- RLS под реальной ролью logistix_app (`verify_rls_task_1_4_9.py`): OK, 28 проверок (migrate_finance dry-run и apply, повтор, сверка, Shadow-зеркало, отвязка строки; B не видит и не меняет A; откат; сброс контекста).
- ruff, `makemigrations --check`: чисто. НЕ запускалось: полный pytest (вне apps/finance, apps/forwarding), frontend, CI.

## Оговорки
- Месячная проверка (п.6) сравнивает прибыль и маржу; число исключённых заказов не сравнивается.
- Проверка п.5 не ограничивается `--month` (заказ целиком).
- Месяц новой доли = дата строки-источника (legacy_line), у новых долей - expense_date.
- Разрешение проблемы вручную не меняет данные: сумма спорной строки остаётся только в старом учёте и явно перечислена в отчёте.
