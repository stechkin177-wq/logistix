# Отчёт по задаче 1.1 (этап 1, финансовая архитектура P0.1)

Статус: DONE (BLOCKED не потребовался, противоречий в требованиях не найдено).
Ветка claude/epic-bohr-380x91, ничего не запушено. Коммиты (от старого к новому):

| Блок | Хеш | Сообщение |
|---|---|---|
| A | 3b790b6 | feat(forwarding): Trip.carrier_price (столбец price) и алиас price в API |
| B | 3018d2c | feat(core): защита системных кодов справочников |
| C | d6547f3 | feat(core): системные коды статусов рейса, миграция данных и команды проверки |
| D | ff9eb8e | feat(forwarding): Trip.completed_at и правила выхода из статуса «Завершён» |

Блок E (проверки и этот отчёт) отдельных изменений кода не потребовал; отчёт лежит в игнорируемом каталоге `.superpowers/`, в коммиты не входит.

## 1. Изменённые файлы (59 файлов относительно 49c8472)

Backend, новые файлы:
- core/handbooks/system_codes.py (реестр системных кодов, исключение SystemValueProtected, проверка check_change, контекст system_code_assignment)
- core/handbooks/status_codes.py (чистая логика однозначного сопоставления статусов)
- core/management/commands/check_system_status_codes.py, assign_system_status_code.py
- forwarding/management/commands/backfill_trip_completed_at.py (+ пакеты management/__init__)
- core/audit/labels.py (подписи полей аудита)
- миграции core/0011_trip_status_codes.py, core/0012_trips_revert_completed_permission.py, forwarding/0006_trip_carrier_price.py, forwarding/0007_trip_completed_at.py
- тесты: core/tests/test_system_codes.py, core/tests/test_trip_status_codes.py, forwarding/tests/test_trip_completion.py, documents/tests/test_carrier_price_keys.py

Backend, изменённые: core/handbooks/{models,api,defaults}.py, core/managers.py (атрибут queryset_class), core/permissions_catalog.py, core/audit/api.py, forwarding/trips/{models,serializers,services,api}.py, finance/trip_expense.py, finance/api/trips.py, documents/{context,catalog}.py; тесты: core/test_roles, core/test_documents_core, documents/test_catalog, finance/test_trip_expense, forwarding/test_trips, forwarding/test_order_views.

Frontend: features/trips/{types,api,hooks}.ts, components/{TripFields,TripDrawer,TripStatusControl}.tsx, pages/TripsPage.tsx, features/consignments/components/CreateTripDrawer.tsx, features/finance/{types.ts,TripExpenseDialog.tsx}, features/settings/handbooks/HandbooksPage.tsx, features/settings/roles/catalog.ts, shared/api/types.ts, shared/i18n/{ru,kk}.json, фикстуры test/{trips,orders,permissions}.ts, тесты TripsPage/ConsignmentsPage/HandbooksPage/RolesPage.

Документация: docs/ops/RUNBOOK.md (раздел «Финансовая архитектура P0.1, задача 1.1: что сделать после обновления»).

## 2. Модели и поля

- Trip.price -> Trip.carrier_price (`DecimalField(..., db_column="price")`, min 0). CheckConstraint `trip_price_gte_0` теперь по carrier_price (то же имя).
- Trip.completed_at: DateTimeField(null=True, blank=True, editable=False) + индекс `trip_company_completed_idx` (company, completed_at).
- HandbookValue: свойство `is_system`, переопределены save()/delete(), свои менеджеры `objects`/`all_objects` с HandbookValueQuerySet (защита массовых delete/update). В core/managers.py BaseManager получил атрибут `queryset_class` (по умолчанию None, поведение прочих моделей не меняется).
- Реестр: `SYSTEM_CODES` (handbook_code -> frozenset): order_status {completed, cancelled}; trip_status {PLANNED, ASSIGNED, IN_PROGRESS, UNLOADING, COMPLETED, CANCELLED}.
- Каталог прав: новое право `trips.revert_completed` в EXTRA_PERMISSIONS (теперь 55 кодов вместо 54). Чтобы не выдать его Бухгалтеру, введён FINANCE_EXTRA_PERMISSIONS (роль «Бухгалтер» получает только его); Администратору право выдаётся (SYSTEM_ROLES["Администратор"] = ALL_PERMISSIONS).

## 3. Миграции

| Миграция | Что делает | Обратимость / данные |
|---|---|---|
| forwarding.0006_trip_carrier_price | SeparateDatabaseAndState: RemoveConstraint, RenameField, AlterField(db_column="price"), AddConstraint только в state; database_operations пусты | БД не меняется. `sqlmigrate` выводит «(no-op)». Проверено: после migrate столбец `price` на месте, `carrier_price` в БД нет, ограничение `trip_price_gte_0` (price >= 0) на месте. Реверс (migrate forwarding 0005) выполняется |
| forwarding.0007_trip_completed_at | AddField completed_at + AddIndex | Схема без данных; обратима |
| core.0011_trip_status_codes | Назначает код значению trip_status только при однозначном сопоставлении (пустой код; ровно одно значение с точным названием, регистр и пробелы строго; признаки is_initial/is_final как у стандартного; код не занят); tenant_context по каждой компании | Обратима как noop (коды не снимаются); идемпотентна |
| core.0012_trips_revert_completed_permission | Дописывает `trips.revert_completed` системным ролям «Администратор» | Обратима как noop; идемпотентна; пользовательские роли и прочие системные не затрагиваются |

`makemigrations --check` чист. Дополнительно прогнана цепочка на отдельной БД: migrate до core.0010, откат, затем применение 0011/0012/0006/0007 на компании с «обнулёнными» кодами и переименованной «Выгрузкой»: назначены 5 из 6 кодов, «Разгрузка» осталась без кода, право есть только у Администратора; реверс migrate core 0010 и forwarding 0005 проходит. Временная БД удалена.

## 4. Обратная совместимость

- Старый клиент, присылающий только `price` (создание и PATCH), работает: тесты `test_old_client_sending_only_price_still_works`, сервисный вызов `create_trip(data={"price": ...})`.
- В ответе рейса всегда оба поля с одинаковым значением (`carrier_price` и `price`); в finance-эндпоинте expense-lines в `trip` тоже оба.
- `price` и `carrier_price` в одном запросе с разными значениями (сравнение Decimal) -> 400, ошибка на `price`; равные значения в разной записи ("10" и "10.00") допускаются.
- Документы: ключи `trip.price`, `trip.price_words` сохранены (описание «устарело, используйте carrier_price»), добавлены `trip.carrier_price`, `trip.carrier_price_words`. Шаблон со старым `{{ trip.price }}` рендерится; starter.py не менялся.
- Аудит: новые записи пишут ключ `carrier_price` (snapshot по attname), старые с `price` не изменялись. Отображение подписи: единственный потребитель аудита сейчас - API `/api/audit/` (во frontend страницы аудита нет, grep по web/src подтвердил). В ответ добавлено поле `changes_labels` (core/audit/labels.py) с подписью «Стоимость перевозчика» для обоих ключей `price` и `carrier_price` объекта forwarding.trip (плюс подписи для completed_at, status_id, reason). Само `changes` не тронуто.
- Новые системные значения справочников: значения без кода и пользовательские значения не затронуты.

## 5. Изменённые API

- Trips (`/api/trips/`): поля `carrier_price` (основное), `price` (алиас чтения и записи), `completed_at` (только чтение, ISO; в любом запросе -> 400, как number/status). `POST /api/trips/{id}/status/`: новое необязательное поле `reason`; обязательно при выходе из COMPLETED; без права `trips.revert_completed` выход -> 403; без причины -> 400 {"reason": [...]}.
- `GET/POST /api/finance/trips/{id}/expense-lines/`: в `trip` добавлен `carrier_price` (старый `price` сохранён).
- Handbook values (`/api/handbook-values/`, `/api/handbooks/?code=`): новое поле `is_system` (read-only). Для системных значений ответ 400 на: смену code, delete, is_active=false, смену is_final, перенос в другой справочник; 400 на присвоение зарезервированного кода несистемному значению (в том числе при создании).
- `/api/audit/`: новое поле `changes_labels`.
- Management-команды: `check_system_status_codes [--company ID]`, `assign_system_status_code --company ID --value ID --code CODE [--dry-run]`, `backfill_trip_completed_at [--company ID] [--dry-run]`.

## 6. Тесты и результаты запусков

Новые backend-тесты (77 штук сверх базы 1535):
- A: documents/test_carrier_price_keys.py (6: каталог, контекст, старый и новый шаблоны, пример контекста); в forwarding/test_trips.py 11 новых (оба поля в ответе, только price, только carrier_price, равные значения, конфликт -> 400, отрицательные/мусор для обоих, сервис с обоими ключами и конфликтом, столбец `price` и ограничение в БД, ключ аудита и подписи, API аудита); обновлён паритет каталога и контекста (test_catalog), expense-lines (test_trip_expense).
- B: core/test_system_codes.py (19: реестр, is_system, каждое запрещённое действие через API с проверкой неизменности данных, разрешённое переименование и порядок, резерв кода при отсутствующем системном значении, прямой model.delete(), queryset delete/update, save, контекст назначения).
- C: core/test_trip_status_codes.py (22: значения по умолчанию, миграция на стандартной / переименованной / дубликаты / регистр и пробелы / иные признаки / занятый код / чужой код / несколько компаний / идемпотентность, обе команды, dry-run, ошибки).
- D: forwarding/test_trip_completion.py (19: completed_at при завершении и неперезапись, выход с причиной/без причины/без права, обнуление и аудит, повторное завершение, отмена незавершённого без новых требований и без создания записей, completed_at не принимается, право только у Администратора, миграция 0012, backfill: последняя запись аудита, отсутствие записи -> «требует проверки», dry-run, повтор, фильтр компании).
- Обновлены честно (без ослабления): число прав 54 -> 55 (test_roles, test_documents_core) и добавлена проверка, что право `trips.revert_completed` есть только у «Администратор»; два существующих теста, деактивировавших системные статусы («Отменён» заказа, «Выгрузка» рейса), переведены на несистемные статусы, потому что действие теперь запрещено намеренно.

Frontend: 6 новых тестов (carrier_price в карточке и списке; тело POST/PATCH без устаревшего `price`; диалог причины при выходе из «Завершён»; отключённые опции без права; обычный переход без причины; completed_at в карточке; is_system в справочниках); обновлены тесты форм под подпись «Стоимость перевозчика» и каталог прав (55 чекбоксов).

Результаты (реальные):
- ruff check: All checks passed; ruff format --check: 207 files already formatted.
- pytest apps/documents: 393 passed (96,9 с)
- pytest apps/forwarding: 437 passed (209 с)
- pytest apps/finance: 113 passed (49 с)
- pytest apps/core: 614 passed (172 с)
- полный pytest: 1612 passed (9 мин 20 с); база до работ - 1535 passed
- manage.py makemigrations --check: No changes detected
- web: `npm run lint` без замечаний; `npx tsc -b` без ошибок; `npx vitest run`: 44 файла, 409 passed (до работ 403); `npm run build`: успешно (предупреждение Vite о размере чанка 703 kB уже было и к задаче не относится).

## 7. Нерешённое, риски, отклонения от брифа

1. Пока системный код COMPLETED не назначен значению «Завершён» компании (переименовано/неоднозначно), правила completed_at и защиты выхода из «Завершён» для неё не действуют; такие компании видны в `check_system_status_codes`, назначение выполняет владелец платформы командой `assign_system_status_code`. Для всех новых компаний и стандартных старых коды ставятся автоматически.
2. `assign_system_status_code` ограничена справочником trip_status (как в брифе); при нестандартных признаках значения выдаёт предупреждение, но назначает (решение владельца платформы). Запись аудита без пользователя (source=assign_system_status_code в changes).
3. `backfill_trip_completed_at` пишет только Trip.completed_at (queryset update, updated_at не трогает) и не пишет аудит о самом backfill; сводка в stdout.
4. Попытка присвоить несистемному значению код из реестра при уже занятом коде возвращает стандартную ошибку DRF о нарушении уникальности пары (handbook, code) (non_field_errors), а не поле `code`; для свободного зарезервированного кода ошибка идёт на поле `code`. Статус 400 в обоих случаях.
5. Массовый `QuerySet.update(is_active/is_final/code=...)` по строкам, среди которых есть системные, теперь запрещён целиком (SystemValueProtected). Прямой SQL и bulk_create/bulk_update защиту обходят (ограничение Django); сидинг использует bulk_create намеренно.
6. completed_at в теле запроса отвергается 400 (как number/status), а не молча игнорируется; клиент, присылающий весь объект рейса в PATCH, получит 400 (текущий frontend шлёт только редактируемые поля).
7. Подпись аудита реализована на backend (поле `changes_labels` в `/api/audit/`), так как во frontend просмотра аудита нет; отдельная страница журнала не создавалась (вне задания).
8. Frontend: форма рейса использует ключ `carrier_price`; серверная ошибка по алиасу `price` не привязывается к полю (frontend `price` не отправляет). Ключ i18n `trips.price` сохранён.
9. Ограничение окружения: Postgres и Redis при старте были остановлены, я запустил их (`pg_ctlcluster 16 main start`, `redis-server --daemonize yes`). Миграции проверены на владельце БД (суперпользователь), политики RLS при этом обходятся; поведение под ролью приложения покрыто существующими RLS-тестами и общим прогоном.

---

# Fix round 1 (замечания заказчика при приёмке)

Статус: DONE. Коммиты: bcaae4e (п. 1-2), 09a09f6 (п. 3-4), dddd014 (п. 5-6), fbcf3ae (п. 7). Не слито в main, не запушено, демо и демо-база не затрагивались (все проверки миграций - на временных БД, удалены).
Отклонение от формата: п. 1 и 2 в одном коммите, так как правила и тесты неразделимы по коду.

## 1. is_initial
- У системного значения is_initial менять нельзя в обе стороны (API, save, update, bulk_update); name/order правятся свободно.
- make_initial (сервис и действие API) на другое значение запрещён, пока начальное системное: 400 «Начальный статус «Планируется» системный: назначить начальным другое значение нельзя». Правило «ровно одно начальное» и перенос начального в несистемных справочниках (consignment_status, начальный «Новый» в order_status) работают (тесты).
- Интерфейс: флажок «Начальное значение» заблокирован у системных, «Сделать начальным» скрыта, пока начальное системное; frontend-тест.

## 2. Обходы защиты (все негативные тесты через ORM, данные в БД после попытки неизменны: core/tests/test_system_bypass.py, 33 теста)
Единый check_change(старая строка БД, новое состояние). Закрыто:
- QuerySet.update(): состояние до и после в одной транзакции (атомарно, откат при нарушении), поэтому работает и для выражений Case/F/Value и для bulk_update (он вызывает update()). Поля: code, is_active, is_final, is_initial, handbook(_id).
- bulk_update(): is_active/is_final/code/is_initial/handbook, смешанный пакет откатывается целиком; name/order разрешены.
- bulk_create(): резервный код запрещён; update_conflicts (upsert) запрещён целиком; update_conflicts для существующего pk (тесты).
- QuerySet.delete() (objects, all_objects, `_default_manager`, связанный менеджер `handbook.values`), model.delete().
- save(): с update_fields и без, смена handbook, новый объект с pk существующей системной строки (перезапись) запрещены.
- get_or_create/update_or_create: через create/save, покрыты тестами.
- Устаревший экземпляр: save/delete сверяются со строкой БД, а не с атрибутами (тест: в памяти код пуст, в БД системный).
- Оба менеджера: общий HandbookValueQuerySet (queryset_class) на objects и all_objects.
- Внутренние обходы, только явные контекстные менеджеры: system_code_assignment() (сидинг компании и команда ручного назначения; разрешает присвоить резервный код при создании/назначении) и system_values_maintenance() (полный обход для служебного удаления/очистки; в коде приложения никто не использует, т.к. удаления компании с её справочниками в приложении нет: FK на Company = PROTECT; покрыт тестом, после выхода защита снова действует).
- Известные ограничения Django: raw SQL, `QuerySet._raw_delete`, TRUNCATE (очистка тестовой БД pytest-django) защиту обходят; `_base_manager` (простой Manager, для доступа по FK) не защищён, менять base_manager_name не стал, чтобы не создавать лишнюю миграцию состояния.
- Побочное изменение поведения: прямая попытка присвоить уже занятый резервный код теперь даёт IntegrityError (ограничение БД) раньше SystemValueProtected, в API это по-прежнему 400.

## 3. Миграции независимы от кода приложения
- core.0011, core.0012, forwarding.0006, forwarding.0007: импортов из apps.* нет (тест по AST). Константы, список специй статусов, алгоритм сопоставления и имя права/роли вписаны внутрь.
- tenant_context заменён встроенной установкой `set_config('app.company_id', ..., false)` на соединении миграции с обязательным сбросом в `finally` (старые миграции 0009/0010 продолжают пользоваться tenant_context как общей инфраструктурой, их не трогал). Обоснование: действующий apps.core.tenancy/rls может измениться, миграция не должна зависеть от него. Тест проверяет, что GUC после миграции пуст.
- system_code_assignment в миграции не нужен (исторические модели без guard); тесты теперь запускают миграцию на реальных ИСТОРИЧЕСКИХ моделях (MigrationExecutor.project_state), а не на текущих.
- Тест с подменённым реестром SYSTEM_CODES, SPECS и ALL_PERMISSIONS/дефолтами: результат прежний; сценарии: стандартная, переименованная, дубликаты/признаки/занятый код (прежние тесты), повторное применение.

## 4. Условие «компания не сопоставлена» и unmapped_system_codes
Компания считается НЕ сопоставленной по trip_status, если выполняется хотя бы одно: (а) справочника trip_status или его значений нет; (б) хотя бы один из шести кодов PLANNED, ASSIGNED, IN_PROGRESS, UNLOADING, COMPLETED, CANCELLED не назначен ни одному значению (статус переименован, дубликаты по названию, иные признаки is_initial/is_final, код занят, значение с другим кодом). Определяется функцией `apps.core.handbooks.services.unmapped_system_codes(company, handbook_code="trip_status") -> list[str]` (отсортированный список отсутствующих кодов; пусто = сопоставлена; та же функция работает для order_status). Для engine=new: переключать нельзя, пока список не пуст. Тесты (4): стандартная, частично, после ручного назначения, без справочника, изоляция компаний. Само переключение и completed_status не реализованы.

## 5. trips.revert_completed
Сквозные тесты: роль «Старший диспетчер» создаётся штатным POST /api/roles/ с правом, пользователь выходит из COMPLETED (без причины 400, с причиной 200, completed_at обнулён); та же роль без права: 403, данные неизменны; право добавляется к существующей роли PATCH /api/roles/{id}/ и действует; роль с roles.* без права не может выдать его (ensure_can_grant, 400/403). Frontend: чекбокс «Рейсы: выводить рейс из статуса «Завершён»» в матрице сохраняется (POST с permissions) и блокируется, если у самого пользователя права нет.

## 6. backfill_trip_completed_at
Order.completed_at не используется; ограничение добавлено в help команды и docstring модуля. Тесты: заказ с двумя рейсами и заполненным Order.completed_at без записей аудита - completed_at рейсов остаётся пустым, оба рейса в отчёте «требует проверки»; проверка текста help/docstring.

## 7. Финальные проверки (реальные результаты)
- ruff check: чисто; ruff format --check: 210 files already formatted; makemigrations --check: No changes detected.
- Один полный pytest: 1659 passed (9 мин 57 с). Было 1612 после первого захода.
- web: lint чисто, tsc -b чисто, vitest 44 файла / 412 passed (было 409), build успешен.
- (а) Чистая БД: migrate с нуля, откат forwarding -> 0005 и core -> 0010 (0007, 0006, 0012, 0011 откатываются), повторное применение: все OK; makemigrations --check чист. БД удалена.
- (б) Данные ДО 1.1: backend/scripts/verify_upgrade_task_1_1.py (+ обёртка-тест apps/core/tests/test_upgrade_script.py, входит в полный прогон): временная БД, migrate до core.0010 и forwarding.0005 (проверяется отсутствие completed_at и core.0011), две компании (стандартные статусы без кодов; «Выгрузка» переименована в «Разгрузка»), три рейса с price (100.50, 0.00, 777777.77) в каждой, роли (системные без нового права, пользовательская «Своя роль»). После обновления: price сохранены дословно, столбец price есть, carrier_price нет, trip_price_gte_0 на месте, completed_at пусто у старых рейсов; коды: стандартная 6/6, переименованная 5/6 («Разгрузка» без кода) и она видна в отчёте check_system_status_codes («UNLOADING: НЕ назначен»); право получил только «Администратор». Затем откат (forwarding 0005, core 0010), повторное применение и повторная проверка: OK (13 с). БД удаляется в finally.
- Сквозные сценарии рейса через API (test_end_to_end_trip_scenario_via_api и ранее добавленные): создание старым (только price) и новым клиентом, конфликт 400, завершение, повторное завершение (400, completed_at не изменился), выход из COMPLETED (без причины 400, право+причина, completed_at обнулён, аудит со старым значением). Шаблоны документов со `{{ trip.price }}`/`{{ trip.price_words }}` и с carrier_price рендерятся (documents/test_carrier_price_keys.py).

## Не удалось / оговорки
- `manage.py check_rls` в этой среде не проходит по причине окружения: роль БД logistix - суперпользователь (RLS у неё не действует); политики RLS проверяются существующими тестами test_rls.
- Миграции проверялись от имени суперпользователя БД, поэтому корректность set_config-пути под непривилегированной ролью приложения прямо не проверена (политика WITH CHECK работает так же, как у старых миграций через tenant_context, но под logistix_app миграции не запускались).
