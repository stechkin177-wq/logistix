# Отчёт 1.4.6: связи со счетами

Статус: **DONE**. Миграций нет. Не пушилось.

## Файлы
Новые: `finance/invoice_links.py`, `finance/tests/test_invoice_links.py` (13 тестов), `backend/scripts/verify_rls_task_1_4_6.py`, `core/tests/test_rls_script_1_4_6.py`. Изменён `finance/invoices.py` (минимально): `_order_income` -> `invoice_links.order_income_total`; `cancel` блокирует Income/Expense до счёта и пишет в аудит отмены освобождённые связи.

## Реализация
- `order_income_total`: engine='new' - Σ Income заказа (не void, в валюте заказа, planned допустим); иначе прежний расчёт по OrderService (legacy/shadow не меняются).
- `link_item_to_income` (только исходящий счёт; тот же заказ/компания, валюта, не void, один Income - не более чем в одном активном счёте -> `item_already_invoiced`; `line` не трогается; идемпотентно).
- `link_expense_to_item` / `unlink_expense_from_item` (только входящий; валюта, перевозчик, рейс; amount > 0; Σ связей позиции <= amount_net (`link_exceeds_item`); частичные суммы; после изменения пересчёт needs_review/invoice_variance; ничего не блокируется).
- Отмена счёта: out-позиции теряют income (прежняя связь - в аудит), in-связи получают released_at/release_reason, история остаётся, снимки позиции (title, amount_net) целы, флаги расхождения пересчитываются. В legacy-компаниях без связей аудит отмены прежний (тест).
- Блокировки: Income/Expense -> Invoice; при отмене Income/Expense блокируются до счёта (`lock_for_cancel`).

## Тесты (реальные результаты)
- `test_invoice_links.py`: 13 passed (аванс по planned, превышение дохода заказа при new и прежний расчёт при legacy/shadow, частичная оплата, повторное включение дохода, отмена счёта и повторное использование, один счёт на несколько расходов и расход на несколько счетов, расхождение -> needs_review, платежи не создают сущности и не меняются при смене цены рейса, изоляция).
- `verify_rls_task_1_4_6.py` под реальной ролью logistix_app (сценарий П2: engine=new, признание дохода, расход перевозчика с долями, входящий счёт и связь, пересчёт цены, отмена; B не видит/не меняет/не удаляет и сервисы не находят чужое; откат; сброс контекста): OK, 42 проверки. Обёртка-тест в core/tests.
- Итог П2 одним прогоном `pytest apps/finance apps/forwarding apps/core/tests/test_rls_script_1_4_6.py apps/core/tests/test_rls_script_1_4_3.py`: **720 passed**. ruff, `makemigrations --check`: чисто.
- НЕ запускалось: полный pytest (остальной apps/core, billing, documents), frontend, CI.

## Риски и оговорки
- Проверка «Σ связей позиции <= amount_net» добавлена сверх ТЗ (защита от двойного покрытия); при несогласии убирается одной строкой.
- Платёж не пересчитывает ничего; связи счёт-доход не используются при подсчёте долга клиента (прежний расчёт по счетам).
- Существующая проверка позиций счёта по `line` не менялась: счёт по новым Income создаётся пока через те же строки заказа, поле `income` заполняется `link_item_to_income`.
