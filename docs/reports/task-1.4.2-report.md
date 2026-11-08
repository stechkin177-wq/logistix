# Отчёт 1.4.2: валютный слой

Статус: **DONE**. Миграций нет (модели из 1.4.1). Не пушилось.

## Изменённые файлы
- `backend/apps/finance/fx.py` (новый), `backend/apps/finance/tests/test_fx.py` (новый, 20 тестов).

## Реализация
- `resolve_rate(company, from, to, on_date)` -> (Decimal, source, rate_date): same; direct (прямая пара или обратная как 1/курс, из двух берётся более свежая, при равенстве - прямая); via_kzt = курс(from->KZT)/курс(to->KZT), нога KZT = 1, дата - более ранняя из ног; нет данных - `FinanceError("rate_missing")`, 409, с кодами валют и датой. Курс квантуется до 6 знаков ROUND_HALF_UP. Курсы читаются только в контексте компании (чужие не видны).
- `fx_snapshot`, `apply_snapshot`, `legacy_missing_snapshot`; деньги через `quantize_money`; нет базовой валюты - `base_currency_missing` (409).
- `change_base_currency(company, new_currency, user, reason)`: только KZT/RUB/USD/EUR из справочника валют своей компании (`base_currency_invalid`), причина обязательна (`reason_required`), `select_for_update` строки настроек в транзакции, проверка курса на сегодня (часовой пояс компании) между каждой используемой валютой (Order, Trip, Invoice, Income, Expense, включая удалённые в корзину) и новой базовой, иначе 409 `rate_missing` со списком пар и без изменений; успех пишет аудит (старое/новое id валюты, reason, user), `updated_by`; история не пересчитывается; повтор той же валюты - без аудита.
- Оговорка: курс X->KZT и KZT->X по буквальному ТЗ получает источник `via_kzt` (нога KZT=1), а не `direct`.

## Тесты (реальные результаты)
- `pytest apps/finance/tests/test_fx.py`: 20 passed (same/direct/inverse/via_kzt/missing, разные даты, округление и копейки, USD->RUB через KZT, изоляция компаний, снимки неизменны при добавлении/изменении/удалении курсов, смена базы: успех, rate_missing, запрещённая валюта, чужая компания, без reason, конкурентные вызовы - непрерывная цепочка аудита).
- `pytest apps/finance`: 177 passed. ruff check/format, `makemigrations --check`: чисто.
- НЕ запускалось: полный pytest, apps/core и apps/forwarding (код 1.4.2 их не затрагивает), frontend, CI, RLS-скрипты (новых таблиц и миграций нет).

## Риски
- Проверка курса при смене базы не учитывает старую базовую валюту и валюты только в платежах/позициях (платёж идёт в валюте счёта).
- Право finance.manage_settings проверяется на уровне API (1.4.12), сервис получает user.
