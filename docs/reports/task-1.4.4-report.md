# Отчёт 1.4.4: доходы

Статус: **DONE**. Миграций нет. Не пушилось.

## Файлы
Новые: `finance/income.py`, `finance/hooks.py`, `finance/engine.py`, `finance/tests/test_income.py` (26 тестов), `finance/tests/p2_helpers.py`.
Изменены (только хуки, спят при engine != 'new'): `forwarding/orders/services.py` (создание заказа), `orders/serializers.py` (смена client_rate), `trips/services.py` (`change_trip_status`, `reassign`; новые необязательные kwargs perms/adjust_reason), `trips/serializers.py`, `trips/api.py` (передача прав и adjust_reason).

## Реализация
`sync_planned_freight`, `recognize_order_income`, `unrecognize_order_income`, `reconcile_order_income` (признать или вернуть по состоянию рейсов), `plan_service`, `mark_service_delivered`, `confirm_service`, `adjust_recognized_income`, `void_income`. Блокировки: Order -> Trip -> Income. Действующие рейсы: не удалённые, не CANCELLED, грузы не удалены. Условие: есть рейс, все в completed_status и с completed_at; нет completed_status -> 409 `completed_status_missing`. recognized_on - дата самого позднего завершения в часовом поясе компании; trip - последний завершивший; IncomeTrip = все завершившие; FX-снимок на recognized_on (нет курса -> 409 rate_missing, транзакция рейса откатывается). Повторные вызовы - no-op. Возврат в planned очищает дату, основание, рейс и FX; IncomeTrip остаются и пишутся в аудит. Закрытый период проверяется при признании (системно) и возврате (can_adjust + reason). Хуки пробрасывают ошибки: в engine=new финансовая ошибка откатывает основную операцию.

## Интерпретации, требующие подтверждения заказчика
- Дата признания услуги = дата фактического оказания (delivered_on), а не дата подтверждения.
- Категория/название планового дохода перевозки: «Перевозка {номер заказа}».
- После void планового freight следующий sync создаёт новый planned (разрешено частичным unique).
- Состав рейса (reassign) тоже пересчитывает признание у прежних и новых заказов.

## Тесты (реальные результаты)
- `pytest apps/finance/tests/test_income.py`: 26 passed (один/несколько/сборные рейсы, отмена части и всех, повтор, возврат и повторное завершение, конкурентные потоки - один Income, client_rate до/после признания, услуги, нет курса, закрытый период, нет completed_status, откат при ошибке хука, legacy/shadow спят, изоляция).
- `pytest apps/forwarding`: 443 passed (хуки ничего не сломали). ruff, `makemigrations --check`: чисто.
- НЕ запускалось: полный pytest, apps/core, frontend, CI, RLS под logistix_app (общий прогон для сервисов П2 - в конце П2).

## Риски
- Удаление рейса/заказа в корзину доход не пересчитывает (хук только на статус, состав и client_rate).
- Хук после смены статуса обходит заказы рейса по одному; много заказов в сборном рейсе = несколько блокировок подряд (по возрастанию pk).
