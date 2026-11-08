# Отчёт 1.4.12: API и интерфейс

Статус: **DONE**. Коммиты bc70fc2 (backend), 52017d9 (web). Миграций нет. Не пушилось.

## Backend (apps/finance/api/ledger.py, admin.py; config/urls.py)
Эндпоинты и права (проверки на сервере, ошибки {detail, code}):
- `GET /api/finance/engine/` (finance.view) - engine, заморозка, базовая валюта.
- `/api/finance/incomes/`: список (order, status, kind, currency, date_from/to), карточка (finance.view); POST создание плановой услуги (finance.create); `POST {id}/deliver|confirm|adjust` (finance.update), `void` (finance.delete).
- `/api/finance/expenses/`: список (trip, order, category, status, needs_review, даты; с долями, остатком и расхождением со счётом без N+1), POST ручной (create), PATCH ограниченный - только title и category (update; остальное 400 field_not_editable), `PUT {id}/allocations/` (update), `POST void` (delete), `link-invoice-item` / `unlink-invoice-item` (update).
- `POST /api/finance/trips/{id}/carrier-expense/` (create): new - Expense; legacy/shadow - прежние строки через `create_trip_expense` (подсказка по заказам рейса, если доли не переданы).
- `GET|PATCH /api/finance/settings/`, `GET|POST /api/finance/settings/status-mapping/` (finance.manage_settings); смена базовой валюты через `change_base_currency` с `reason`.
- `GET|POST /api/finance/periods/` (список view / close - finance.close_period), `POST /api/finance/periods/{id}/reopen/` (finance.reopen_period, причина).
- `GET /api/finance/migration/`, `POST /api/finance/migration/issues/{id}/resolve/` (finance.manage_settings; решение по замечанию 0.1).
- `GET /api/orders/{id}/finance/`, `GET /api/trips/{id}/finance/` (finance.view).
Коды: period_closed, backdating_forbidden, finance_frozen, rate_missing, legacy_lines_readonly и др. Старые эндпоинты не менялись (проверено тестом).
Тесты `test_finance_api.py` - 20 passed: права по ролям, ошибки period_closed/backdating_forbidden/finance_frozen/rate_missing, изоляция компаний (доходы, расходы, периоды, миграция, сопоставление статусов), без N+1, legacy-совместимость.

## Frontend
Новые: `ledgerTypes/Api/Hooks`, `IncomesTab`, `ExpensesTab`, `FieldsDialog`, `LedgerBadges`, `OrderFinanceBlock`, `TripFinanceBlock`, `FinanceSettingsPage` (маршрут `/settings/finance`, пункт меню под finance.manage_settings). Изменены: `FinancePage` (вкладки «Доходы»/«Расходы» только при engine=new; прямая ссылка при legacy возвращает к счетам), `orders/FinanceTab` (блок + строки только для чтения в new), `trips/TripDrawer`, `shared/api/errors.ts` (новые коды), i18n ru/kk.
Тесты vitest: `Ledger.test.tsx` (7), `FinanceSettings.test.tsx` (5), `FinanceCards.test.tsx` (5): отображение по engine, права, отправка форм, защита от двойной отправки, коды ошибок, изоляция по правам. Вместе с затронутыми (`src/features/finance|orders|trips`, layout, settings, i18n, api, app): 63 + 170 passed; eslint (весь src, --max-warnings 0) и `tsc -b --noEmit` чисто. НЕ запускалось: полный vitest, build, CI.

## Интерпретации / оговорки
- Признак режима для интерфейса - отдельный лёгкий `/api/finance/engine/` (core не импортирует finance); полный набор полей - в `/api/finance/settings/`.
- Создание плановой услуги в интерфейсе принимает id заказа числом (выбора заказа из списка нет).
- Ручное создание расхода: категория и валюта берутся из справочников (нужен handbooks.view).
- Журнал операций в new отдаёт строковые id вида `income:12` / `expense:34`.
- Страницы «Доходы/Расходы» не имеют выбора долей в интерфейсе (долевое распределение - через API PUT allocations); панель долей только для просмотра.
- RLS-скрипта для API-слоя нет (по брифу); изоляция проверена тестами API.
