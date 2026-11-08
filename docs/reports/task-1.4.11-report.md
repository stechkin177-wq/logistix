# Отчёт 1.4.11: переключение, чтение из новой модели, защита OrderService, заморозка

Статус: **DONE**. Коммит bdbdd3d (замечания к П3 - отдельным коммитом adfd99b ДО него). Не пушилось, engine ни у одной реальной компании не менялся (только тестовые данные).

## Изменённые файлы
Новые: `finance/switching.py`; команды `switch_finance_engine`, `rollback_finance_engine`, `freeze_finance`; миграция `finance/0009_settings_switch_freeze` (engine_switched_at, financial_writes_frozen; `db_default=False`, чтобы историческая функция миграции 0007 работала на текущей схеме); `scripts/verify_rls_task_1_4_11.py` + обёртка `core/tests/test_rls_script_1_4_11.py`; `finance/tests/test_switching.py` (24 теста).
Изменены: `engine.py` (`use_new_engine`, `assert_legacy_lines_writable`), `periods.py` (`assert_finance_writable`), `reports_new.py` (аннотация итогов заказов, журнал и сводка по новым сущностям), `operations.py` (`journal_rows`, `journal_summary`), `api/operations.py`, `summary.py`, `forwarding/dashboard.py` (`_month_finance` -> new; `_month_finance_legacy`), `forwarding/finance_lines/services.py` (`order_totals`/`annotate_order_totals` выбирают источник; `*_legacy`; `sync_base_line` в new не пишет), `finance_lines/api.py` (409 legacy_lines_readonly, 423), `trip_expense.py`, `shadow.py`, `migration.py`, `reconcile.py` (старая сторона сверки всегда legacy-функции), сервисы income/expenses/invoice_links/invoices/payments (вызов `assert_finance_writable`).

## Поведение
- Переключение `shadow -> new` проверяет кодом: engine=shadow; cutover; `--approval-ref`; фонд не заморожен; статусы (1.4.10); сверка success (команда сама запускает reconcile; в dry-run сверка откатывается); нет открытых error-Issue; нет «не отражённых» сумм (замечание 0.1). Отказ - перечень причин. Затем в одной транзакции: правило cutover по доходам перевозки (до cutover не трогаются; после: все рейсы завершены -> признание на дату последнего завершения, basis trip_completed; иначе planned; завершение раньше cutover при строке позже -> Issue `cutover_boundary`, запись как была; закрытый период -> вся операция откатывается), engine=new, cutover_date, engine_switched_at, аудит с approval-ref. Услуги не меняются.
- `legacy -> shadow`: данные не меняются, аудит.
- Откат: ≤30 дней; нет нативных записей (Income без legacy_line, manual_adjustment, Expense без legacy_group_key, void не из-за удаления строки, доли без legacy_line, связи со счетами после переключения); полная сверка success; approval-ref. Ничего не удаляет.
- Заморозка: `FinanceError finance_frozen 423` в income/expenses/invoice_links/issue+cancel счёта/оплатах/расходе рейса/строках заказа/Shadow-зеркале/migrate_order (не dry-run); чтение работает.
- engine=new: чтение итогов заказа/списка/экспорта/дашборда/журнала(+Excel)/плиток из Income и долей; запись в `/api/order-lines/` и `create_trip_expense` -> 409 `legacy_lines_readonly`; `sync_base_line` не пишет. legacy/shadow - как раньше.

## Тесты (что запускалось)
- `test_switching.py` 24 passed: каждое условие gate, dry-run, успех, правило cutover (3 случая) и откат при закрытом периоде, откат (разрешён + все отказы), заморозка (все писатели, чтение, изоляция, shadow), legacy_lines_readonly, эквивалентность чтения (заказы, дашборд, журнал, плитки, Excel), изоляция компаний.
- RLS под `logistix_app`: `verify_rls_task_1_4_11.py` OK, 28 проверок (переключение/откат/заморозка A не затрагивают B).
- Пакетом: `pytest apps/finance apps/core/tests/test_rls_script_1_4_11.py test_rls_script_1_4_9.py test_upgrade_script_1_4_1.py apps/forwarding/tests/test_order_lines.py`: 387 passed. Затронутые forwarding-тесты (`test_shadow`, `test_dashboard`, `test_order_views`, `test_orders`): 206 passed.
- ruff, `makemigrations --check`: чисто. НЕ запускалось: полный pytest, CI.

## Оговорки / интерпретации
- В тестах счётчиков запросов (`LIST_QUERY_BOUND` 10->11, дашборд 13->14, экспорт 10->11 и 7->8) добавлен один запрос определения режима учёта; число запросов по-прежнему не зависит от размера данных.
- Журнал в new: доход и расход одной старой строки - две строки журнала; число «строк без курса» в сводке считается по этим строкам. Плановый доход без даты попадает в журнал по дате создания. Итоги/по валютам эквивалентны (проверено).
- Базовая валюта в отчётах/сводках остаётся KZT-константой (как в старых отчётах и reports_new 1.4.9): перевод отчётов на произвольную базовую валюту не делался.
- После переключения доходы, переоценённые правилом cutover, расходятся с legacy-строками: откат по условию (в) тогда откажет по сверке (консервативно).
- Сверка в dry-run выполняется в откатываемой транзакции (журнал запусков не меняется).
- Вызов `assert_finance_writable` НЕ стоит в черновиках счетов (create/update/delete draft): они не меняют учёт.
- RLS-прогон по каждой новой миграции (0008, 0009): отдельного пошагового скрипта нет; таблицы уже под RLS, колонки добавлены к существующим; поведение под ролью проверено итоговым скриптом 1.4.11 и обёрткой 1.4.9.
