# Отчёт 1.4.10: сопоставление статусов и completed_status

Статус: **DONE**. Коммит b49da41. Миграций нет. Не пушилось.

Файлы: `finance/status_mapping.py` (новый), `finance/tests/test_status_mapping.py` (11 тестов).
- `map_system_status(company, value, code, *, user)`: значение trip_status своей компании (чужое -> 404 status_not_found), активное, без кода; код из реестра и свободен; под `system_code_assignment()`; аудит; идемпотентно; другой код у значения -> 409 status_already_coded; занятый код -> 409 status_code_taken. Код COMPLETED автоматически выставляет `completed_status` (с аудитом).
- `status_mapping_report(company)`: значения (id, имя, код, активно, is_final, is_initial), `unmapped` с кандидатами (только подсказка), `completed_status`, `switch_blocked`, `blockers`.
- `switch_blockers(company)`: unmapped_system_codes, duplicate_system_codes (отдельная проверка «ровно одно значение на код»), completed_status пуст / не указывает на активное значение с кодом COMPLETED. Используется условием переключения (1.4.11).
Интерпретация: `update_settings` по-прежнему позволяет выбрать любой активный статус (старый тест 1.4.3); требование «completed_status = значение с кодом COMPLETED» проверяется в отчёте и условии переключения, а не запретом в update_settings.
Тесты: `pytest apps/finance/tests/test_status_mapping.py` 11 passed; ruff чисто. Не запускалось: полный pytest, CI.
