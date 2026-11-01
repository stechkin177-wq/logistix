# Этап 3B. Документы: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Word-шаблоны документов компании с метками, журнал выданных документов с фиксацией данных, скачивание DOCX и PDF, стартовый набор из семи образцов.

**Architecture:** новое приложение `backend/apps/documents` (зависит от `core`, `forwarding`, `finance`; `core` о нём не знает - стартовые шаблоны подключаются сигналом `company_created`). Шаблон - `.docx` с метками Jinja, рендер `docxtpl` в песочнице; выданный документ хранит снимок данных (JSON) и версию шаблона, файл собирается при скачивании. PDF - конвертация DOCX через LibreOffice в отдельном процессе. Фронтенд: страница «Журнал документов», настройки шаблонов, кнопки выдачи в заказе, счёте, рейсе и карточке клиента.

**Tech Stack:** Django 5, DRF, PostgreSQL (RLS), `docxtpl`, `num2words` (ru и kz), `python-docx`, LibreOffice headless; React 19, TypeScript, TanStack Query, i18next, vitest.

**Spec:** `docs/superpowers/specs/2026-11-01-documents-3b-design.md` (читать целиком вместе с планом).

## Global Constraints

- Все новые модели - `TenantModel` с `EnableRLS("documents.<Model>")` в миграции; `manage.py check_rls` проходит. `IssuedDocument` не изменяется и не удаляется после создания.
- Виды документов: `contract`, `order_request`, `carrier_order`, `act`, `invoice_print`, `cmr`, `letter`. Новые виды номеров нумерации: `contract` = `Д-{year}-{index}`, `act` = `АКТ-{year}-{index}`, `carrier_order` = `ЗП-{year}-{index}`, `cmr` = `CMR-{year}-{index}`, `letter` = `ИСХ-{year}-{index}` (по 5 цифр); `order_request` берёт номер заказа, `invoice_print` - номер счёта.
- Шаблон: только `.docx`, до 2 МБ (`2 * 1024 * 1024` байт), после распаковки до 20 МБ (`20 * 1024 * 1024`), без `vbaProject` и без внешних связей (`TargetMode="External"`); рендер только в `jinja2.sandbox.ImmutableSandboxedEnvironment`.
- PDF: LibreOffice, таймаут 60 секунд, одна конвертация одновременно на сервер (блокировка файла), изолированный профиль; нет LibreOffice или сбой - `pdf_unavailable` (HTTP 503), DOCX остаётся доступным.
- Коды ошибок: `template_missing`, `template_invalid`, `template_too_large`, `source_not_ready`, `pdf_unavailable`, `letter_invalid`; формат `{detail, code}` через `DocumentError(code, detail, status_code=400)` (Задача 4).
- Письмо: тема до 255, текст до 20 000 символов, адресат до 255.
- Выбор шаблона при выдаче: активный шаблон вида и языка; `language` в запросе необязателен: по умолчанию язык компании, если для него нет активного шаблона - `ru`. В 3B сидятся только русские шаблоны.
- Права: новый раздел `documents` (view/create/update/delete) в `SECTIONS`; выдача требует доступа к исходному объекту (`orders.view`, `trips.view`, `finance.view`, `clients.view`).
- Все API под `ModuleRequired("forwarding")`, префикс `/api/documents/`. Все тексты интерфейса через i18n, ключи в `ru.json` и `kk.json` одновременно.
- Тесты бэкенда: `cd backend && python -m pytest <path> -v` (PostgreSQL нужен, как в CI; тесты, которые меняют БД из потоков, помечаются `@pytest.mark.django_db(transaction=True, serialized_rollback=True)`). Фронтенд: `cd web && npx vitest run <file>`, `npm run lint`, `npx tsc -b`. Линт бэкенда: `ruff check .` и `ruff format`.
- Коммиты заканчиваются строками `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` и `Claude-Session: https://claude.ai/code/session_01TJdsug1NTZLaDzZhyYrtpE`. Не использовать `git fetch --depth=1`.

## Review Focus

1. Шаблон с вредоносными метками (`{{ ''.__class__.__mro__ }}`, `{{ config }}`, вызовы функций) и с синтаксической ошибкой: при загрузке 400 `template_invalid`, никогда 500 и никакого выполнения кода (Задача 6).
2. `.docx`-«бомба» (малый файл, огромный после распаковки), файл с макросами, файл с внешними связями, не-zip с расширением `.docx`: отклоняются при загрузке (Задача 6).
3. Заказ без грузов, клиент без контактов, рейс без водителя: документ создаётся с пустыми значениями, без 500 (Задача 7, 9).
4. Сумма прописью на границах: 0; 1; 11-14; 21; 100; 1000; 1 000 000; 0,01; 1,5; отрицательные; число с большим количеством цифр (Задача 3).
5. Два одновременных запроса на выдачу акта: разные номера, без пропусков при откате (Задача 9).
6. Скачивание документа после удаления заказа/счёта или правки ставки: файл собирается из снимка, ссылка на источник не нужна (Задача 9, 11).
7. Выдача акта по черновику/отменённому счёту, договора-заявки по рейсу без перевозчика, чужого объекта по id: ошибка, а не молчаливый успех (Задача 9, 11).

---

## Карта файлов

| Файл | Ответственность |
|---|---|
| `backend/apps/documents/{__init__,apps,errors}.py` | приложение, `DocumentError`, подключение сигнала |
| `backend/apps/documents/models.py` | `DocumentTemplate`, `DocumentTemplateVersion`, `IssuedDocument` |
| `backend/apps/documents/words.py` | сумма прописью, дата словами (ru/kk) |
| `backend/apps/documents/catalog.py` | перечень меток по видам, `sample_context(kind, language)` |
| `backend/apps/documents/engine.py` | проверка загруженного `.docx`, `render_docx(...)` |
| `backend/apps/documents/pdf.py` | конвертация DOCX в PDF, `pdf_available()` |
| `backend/apps/documents/context.py` | сбор контекста (снимка) по видам |
| `backend/apps/documents/starter.py` | сборка семи стартовых `.docx`, сидирование |
| `backend/apps/documents/services.py` | загрузка версий, откат, выдача, сборка файла выданного |
| `backend/apps/documents/api/*.py` | сериализаторы, вьюсеты шаблонов и журнала, capabilities |
| `web/src/features/documents/` | типы, API, хуки, настройки шаблонов, журнал, кнопки выдачи |

---

### Task 1: Права раздела `documents`, виды нумерации, сигнал создания компании

**Files:**
- Modify: `backend/apps/core/permissions_catalog.py`, `backend/apps/core/numbering/models.py` (`KIND_CHOICES`), `backend/apps/core/numbering/services.py` (`KINDS`, `DEFAULTS`), `backend/apps/core/services.py` (отправка сигнала)
- Create: `backend/apps/core/signals.py`, `backend/apps/core/migrations/0010_documents_permissions_numbering.py`
- Test: `backend/apps/core/tests/test_documents_core.py`; правка ожиданий в `backend/apps/core/tests/test_roles.py`

**Interfaces:**
- Produces: `SECTIONS` содержит `"documents"` (всего 13 разделов x 4 + 2 особых = 54 права); `KINDS` содержат `contract`, `act`, `carrier_order`, `cmr`, `letter` (`required={"index"}`, `allowed=BASE_PLACEHOLDERS`, шаблоны из Global Constraints); `apps.core.signals.company_created = Signal()` (аргументы: `company`); `create_company_with_defaults` отправляет `company_created.send(sender=Company, company=company)` после всех сидингов, в контексте компании не оставляя состояния.
- Роли: Менеджер, Бухгалтер, Диспетчер получают `documents.view` и `documents.create`; Администратор - все; Наблюдатель - `documents.view` (формула «все .view» уже даёт).

- [ ] **Step 1: Write failing tests** `test_documents_core.py`: `test_documents_section_in_catalog` (`"documents.update" in ALL_PERMISSIONS`, `len(ALL_PERMISSIONS) == 54`); `test_roles_documents_rights` (Менеджер: `documents.view`, `documents.create` есть, `documents.update` нет; Наблюдатель: `documents.view` есть, `documents.create` нет; Механик: ничего); `test_new_company_has_document_numbering` (`NumberingRule` компании имеет 5 новых видов с шаблонами из Global Constraints; `peek_number("act")` даёт `АКТ-<год>-00001`); `test_company_created_signal_sent` (подписчик получает `company` один раз); `test_backfill_adds_rights_and_rules_for_existing_company` (функция `run_backfill(apps)` миграции дописывает права системным ролям и создаёт недостающие правила нумерации, повторный запуск не дублирует, пользовательская роль не меняется).
- [ ] **Step 2: Run** `python -m pytest apps/core/tests/test_documents_core.py -v` - FAIL.
- [ ] **Step 3: Implement** каталог, нумерацию, сигнал, миграцию (`RunPython` с `run_backfill(apps)` в стиле `0009`: `tenant_context(company.id)`, идемпотентно). В `test_roles.py` обновить число прав: сетка 52, всего 54 (проверка `len(ALL_PERMISSIONS) == 54`).
- [ ] **Step 4: Run** `python -m pytest apps/core -q` - PASS (сначала поправить ожидания в `test_roles.py` и `test_numbering.py`, если считают виды номеров).
- [ ] **Step 5: Commit** `feat(core): права documents, виды нумерации документов, сигнал company_created`.

---

### Task 2: Реквизиты контрагента: адрес, банк, IBAN

**Files:**
- Modify: `backend/apps/forwarding/models.py` (`PartyBase`), `backend/apps/forwarding/api.py` (поля сериализаторов клиента и перевозчика, строки 165 и 188)
- Create: `backend/apps/forwarding/migrations/0005_party_requisites.py`
- Test: `backend/apps/forwarding/tests/test_party_requisites.py`

**Interfaces:**
- Produces: `PartyBase.address = CharField(max_length=500, blank=True)`, `PartyBase.bank = CharField(max_length=255, blank=True)`, `PartyBase.iban = CharField(max_length=34, blank=True)` у `Client` и `Carrier`; те же поля в API списка и карточки (чтение и запись); значение IBAN в аудит не пишется: `audit_masked_fields = ("bin_iin", "notes", "iban")`.

- [ ] **Step 1: Write failing tests**: `test_client_requisites_roundtrip` (POST клиента с `address`, `bank`, `iban` -> GET возвращает те же значения); `test_carrier_requisites_roundtrip`; `test_iban_masked_in_audit` (запись аудита для создания не содержит значение IBAN, содержит `"***"`); `test_requisites_optional` (старый запрос без полей создаёт клиента, поля пустые); `test_iban_too_long_is_400` (35 символов -> 400, не 500).
- [ ] **Step 2: Run** `python -m pytest apps/forwarding/tests/test_party_requisites.py -v` - FAIL.
- [ ] **Step 3: Implement** поля и миграцию (`makemigrations`, без RLS - таблицы уже под RLS), добавить в `Meta.fields` обоих сериализаторов.
- [ ] **Step 4: Run** тест и `python -m pytest apps/forwarding -q` - PASS.
- [ ] **Step 5: Commit** `feat(forwarding): адрес, банк и IBAN контрагента`.

---

### Task 3: Сумма прописью и дата словами

**Files:**
- Modify: `backend/pyproject.toml` (зависимости `"docxtpl>=0.20"`, `"num2words>=0.5.14"`), `backend/requirements.txt` (те же две строки, порядок как в файле; тест `test_vercel_config.py` сверяет файлы)
- Create: `backend/apps/documents/{__init__,apps}.py`, `backend/apps/documents/words.py`
- Modify: `backend/config/settings.py` (`INSTALLED_APPS`: `"apps.documents"`)
- Test: `backend/apps/documents/tests/{__init__,test_words}.py`

**Interfaces:**
- Produces: `amount_in_words(amount: Decimal, currency_code: str, language: str) -> str` - целая часть словами + название валюты + дробная часть цифрами «NN»: `1160.50, KZT, ru` -> `«одна тысяча сто шестьдесят тенге 50 тиын»` (форма единицы согласуется по числу; поддержаны коды `KZT` (тенге/тиын), `RUB` (рубль/копейка), `USD` (доллар/цент), `EUR` (евро/цент); неизвестный код - сам код); `language` in {`ru`,`kk`}; `date_long(day: date, language: str) -> str` - `«1 ноября 2026 г.»` / `«2026 жылғы 1 қараша»`; сумма с модулем больше `10**15` - `ValueError`; отрицательная - минус словом.

- [ ] **Step 1: Write failing tests** `test_words.py` (параметризованно): `0 KZT` -> `«ноль тенге 00 тиын»`; `1` -> `«один тенге 00 тиын»`? (мужской род у «тенге» не склоняется - ожидание строго `«один тенге 00 тиын»`); `11`, `12`, `14` -> корректные слова; `21`, `100`, `1000` -> `«одна тысяча тенге 00 тиын»`, `1000000`; `0.01` -> `«ноль тенге 01 тиын»`; `1.5` -> `«один тенге 50 тиын»`; `-5` -> начинается с `«минус»`; `10**16` -> `ValueError`; казахский `1234 KZT kk` содержит `«мың»` и `«теңге»`; `RUB 2` -> `«два рубля 00 копеек»`; `date_long(date(2026,11,1),'ru') == '1 ноября 2026 г.'`.
- [ ] **Step 2: Run** `python -m pytest apps/documents/tests/test_words.py -v` - FAIL.
- [ ] **Step 3: Implement** на `num2words` (`lang="ru"`/`"kz"`), род и форму валюты задаёт таблица внутри модуля; дробную часть округлить `ROUND_HALF_UP` до двух знаков через `Decimal`.
- [ ] **Step 4: Run** тесты, `python -m pytest apps/core/tests/test_vercel_config.py -q`, `ruff check .` - PASS.
- [ ] **Step 5: Commit** `feat(documents): приложение, сумма прописью и дата словами`.

---

### Task 4: Модели шаблонов, версий и выданных документов; `DocumentError`

**Files:**
- Create: `backend/apps/documents/errors.py`, `backend/apps/documents/models.py`, `backend/apps/documents/migrations/{__init__,0001_initial}.py`
- Test: `backend/apps/documents/tests/test_models.py`

**Interfaces:**
- Produces: `DocumentError(code: str, detail: str, status_code: int = 400)` (как `FinanceError`); `KINDS = ["contract","order_request","carrier_order","act","invoice_print","cmr","letter"]`; `NUMBERED_KINDS = ["contract","carrier_order","act","cmr","letter"]`; `DocumentTemplate(kind, name, language, is_active, current_version: FK DocumentTemplateVersion null)`; `DocumentTemplateVersion(template, number, content: BinaryField, sha256, is_starter, uploaded_by, created_at)`; `IssuedDocument(kind, template_version, number, issue_date, language, client, order, trip, invoice (все FK null PROTECT), snapshot: JSONField, created_by, created_at)`.
- Ограничения БД: уникальность `DocumentTemplate` (company, kind, language) среди `is_active=True`; `DocumentTemplateVersion` (template, number); `IssuedDocument` (company, kind, number) при `kind in NUMBERED_KINDS`; `content` не пустой; `kind` из списка.

- [ ] **Step 1: Write failing tests** `test_models.py`: `test_one_active_template_per_kind_language` (второй активный -> `IntegrityError`; неактивный допустим); `test_version_number_unique_per_template`; `test_issued_number_unique_for_numbered_kinds` (два `act` с одним номером -> ошибка; два `order_request` с одним номером допустимы); `test_issued_document_has_snapshot_json` (Decimal в снимке не сериализуется - тест подтверждает, что поле хранит только JSON-примитивы: сохранение `{"a": "1.00"}` читается обратно); `test_rls_tables_covered` (`tables_missing_rls() == []` под ролью приложения, как `test_rls_tables_covered` финансов).
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement** модели, миграция с `EnableRLS` для трёх моделей. **Step 4: Run** `python -m pytest apps/documents apps/core/tests/test_rls.py -q` - PASS.
- [ ] **Step 5: Commit** `feat(documents): модели шаблонов, версий и журнала выданных`.

---

### Task 5: Справочник меток и тестовый контекст

**Files:**
- Create: `backend/apps/documents/catalog.py`
- Test: `backend/apps/documents/tests/test_catalog.py`

**Interfaces:**
- Produces: `placeholders(kind: str) -> list[dict]` - `[{"name": "order.number", "description": "Номер заказа"}, ...]` для вида (включая общие `doc.*`, `company.*`); `sample_context(kind: str, language: str = "ru") -> dict` - полный контекст со всеми метками, списки непустые (по два элемента), строки заполнены; `context_keys(ctx: dict) -> set[str]` - плоский набор путей `a.b`, списки раскрываются как `a[].b`.
- Набор меток (спека, раздел 5): общие `doc.{number,date,date_long}`, `company.{name,bin,address,bank,iban}`; `client`/`carrier` = `{name,bin_iin,type,address,bank,iban,contact.{name,position,phone,email}}`; `order.{number,date,contract_number,client_ref,rate,rate_words,currency,payment_delay_days,comment,manager,consignments[].{name,weight_kg,volume_m3,pallets,load.{city,address,date},unload.{city,address,date}}}`; `trip.{number,price,price_words,currency,vehicle_plate,driver_name,loading.{city,address,date},delivery.{city,address,date},orders[].{number,client},consignments[].{name,weight_kg,volume_m3,pallets,order,load.{city,address,date},unload.{city,address,date}}}`; `invoice.{number,date,due_date,currency,vat_rate,items[].{n,title,amount_net},net,vat,gross,gross_words}`; `letter.{recipient,subject,body}`. Виды: `contract` -> company, client; `order_request` -> company, client, order; `carrier_order` -> company, carrier, trip; `act`/`invoice_print` -> company, client, invoice, order (если есть); `cmr` -> company, carrier, trip; `letter` -> company, letter.

- [ ] **Step 1: Write failing tests**: `test_catalog_names_match_sample_context` (для каждого вида `{p["name"] for p in placeholders(kind)}` равно `context_keys(sample_context(kind))` - единый источник правды); `test_sample_context_lists_nonempty`; `test_unknown_kind_raises` (`ValueError`); `test_every_description_nonempty`.
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement** - описание меток задаётся в одной таблице данных, `sample_context` строится из неё. **Step 4: Run** - PASS.
- [ ] **Step 5: Commit** `feat(documents): справочник меток и тестовый контекст`.

---

### Task 6: Движок шаблонов: проверка файла и безопасный рендер

**Files:**
- Create: `backend/apps/documents/engine.py`
- Test: `backend/apps/documents/tests/test_engine.py`

**Interfaces:**
- Consumes: `sample_context`, `DocumentError`.
- Produces: `validate_upload(data: bytes, kind: str) -> None` - бросает `DocumentError("template_too_large"|"template_invalid", ...)`: размер до 2 МБ; корректный zip и структура OOXML (`[Content_Types].xml`, `word/document.xml`); сумма распакованных размеров до 20 МБ (проверка по `ZipInfo.file_size` до распаковки); нет `vbaProject.bin` и частей `*.bin` макросов; нет связей с `TargetMode="External"` в `*.rels`; затем пробный рендер `sample_context(kind)` со `StrictUndefined`: неизвестная метка -> сообщение с её именем; синтаксическая ошибка -> сообщение со строкой. `render_docx(data: bytes, context: dict) -> bytes` - `docxtpl.DocxTemplate`, `ImmutableSandboxedEnvironment(undefined=Undefined)`: отсутствующие значения дают пустую строку; ошибки песочницы/шаблона -> `DocumentError("template_invalid")`.

- [ ] **Step 1: Write failing tests** (`test_engine.py`; фабрика `make_docx(text_or_body, extra_parts=None)` собирает `.docx` через `python-docx`/`zipfile`): `test_valid_template_passes` ; `test_too_large_rejected` (2 МБ + 1 -> `template_too_large`); `test_not_a_zip_rejected` (байты `b"hello"` с «docx» -> `template_invalid`); `test_zip_bomb_rejected` (малый zip, у части `file_size` 25 МБ по заголовку -> `template_invalid`); `test_macros_rejected` (часть `word/vbaProject.bin`); `test_external_relationship_rejected` (rels с `TargetMode="External"`); `test_unknown_placeholder_rejected` (`{{ order.nope }}` -> сообщение содержит `order.nope`); `test_syntax_error_rejected` (`{% for x in %}`); `test_sandbox_blocks_attribute_walk` (`{{ ''.__class__.__mro__ }}` и `{{ order.number.__class__ }}` -> `template_invalid`, код не выполняется); `test_render_fills_text_and_loop` (метка в тексте и цикл `{%tr for c in order.consignments %}` по таблице -> итоговый DOCX содержит значения всех элементов); `test_render_missing_optional_is_blank` (контекст без `order.comment` -> пустая строка, без ошибки); `test_render_huge_range_is_bounded` (`{% for i in range(10**9) %}x{% endfor %}` -> `template_invalid`, не зависает).
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement.** Основание: проверка по `zipfile.ZipFile.infolist()` без распаковки целиком; пробный рендер - тем же `render_docx` со `StrictUndefined`. **Step 4: Run** - PASS.
- [ ] **Step 5: Commit** `feat(documents): проверка и безопасный рендер шаблонов`.

---

### Task 7: Сбор контекста по видам документов

**Files:**
- Create: `backend/apps/documents/context.py`
- Test: `backend/apps/documents/tests/test_context.py`

**Interfaces:**
- Consumes: `catalog.context_keys`, `words.*`, модели `forwarding`, `finance`, `core.LegalEntity`.
- Produces: `build_context(kind: str, *, client=None, order=None, trip=None, invoice=None, letter: dict | None = None, number: str, issue_date: date, language: str) -> dict` - контекст со всеми метками вида (значения - JSON-примитивы: строки, числа-строки, списки, словари; даты `dd.mm.yyyy`; деньги `1 234 567,89` с неразрывными пробелами заменены обычными); юрлицо компании: юрлицо заказа/счёта, иначе по умолчанию; `contact` - первый контакт контрагента (пустые строки, если нет); отсутствующие значения - пустые строки, списки - пустые.

- [ ] **Step 1: Write failing tests** (фабрики финансов из `apps/finance/tests/helpers.py`): `test_context_keys_match_catalog_for_every_kind` (для каждого вида ключи совпадают с `placeholders(kind)` - тот же набор, что и тестовый контекст); `test_order_request_values` (номер, ставка, `rate_words`, грузы с маршрутом и датами); `test_consolidated_trip_lists_all_orders`; `test_act_values_from_invoice` (позиции с `n` 1..N, `net/vat/gross`, `gross_words`); `test_missing_data_gives_blanks` (заказ без грузов, клиент без контактов и реквизитов, рейс без водителя -> пустые значения, ни одного исключения); `test_snapshot_is_json_serializable` (`json.dumps(ctx)` без `default`); `test_kk_language_uses_kazakh_words`; `test_company_entity_prefers_order_legal_entity`.
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement** по таблице меток каталога; форматирование чисел/дат - маленькие приватные функции модуля. **Step 4: Run** - PASS.
- [ ] **Step 5: Commit** `feat(documents): контекст подстановки по видам документов`.

---

### Task 8: Стартовые шаблоны и сидирование

**Files:**
- Create: `backend/apps/documents/starter.py`, `backend/apps/documents/migrations/0002_seed_starter_templates.py`
- Modify: `backend/apps/documents/apps.py` (подписка на `company_created`)
- Test: `backend/apps/documents/tests/test_starter.py`

**Interfaces:**
- Consumes: `engine.validate_upload`, `engine.render_docx`, `catalog.sample_context`, `core.signals.company_created`.
- Produces: `starter_bytes(kind: str, language: str = "ru") -> bytes` (собирает `.docx` кодом через `python-docx` с метками; таблицы с `{%tr for ... %}`; в начале каждого шаблона строка-пометка «ОБРАЗЕЦ - проверьте формулировки у юриста перед использованием»); `STARTER_NAMES: dict[str, str]` (`contract` «Договор перевозки (экспедирования)», `order_request` «Заявка клиента», `carrier_order` «Договор-заявка перевозчику», `act` «Акт выполненных работ», `invoice_print` «Счёт на оплату», `cmr` «CMR (товарно-транспортная накладная)», `letter` «Письмо на бланке»); `seed_starter_templates(company) -> None` - идемпотентно создаёт для компании по шаблону на вид (`language="ru"`, `is_active=True`, версия 1 с `is_starter=True`, `current_version`), в `tenant_context`; подписчик сигнала вызывает её при создании компании; миграция `0002` засевает существующие компании (`run_backfill(apps)`).

- [ ] **Step 1: Write failing tests**: `test_each_starter_passes_validation` (для всех 7 видов `validate_upload(starter_bytes(kind), kind)` без ошибок); `test_each_starter_renders_with_sample_context` (результат непустой `.docx`, содержит ключевое значение вида: номер документа и название клиента/перевозчика/получателя письма); `test_starter_contains_disclaimer`; `test_seed_is_idempotent_and_complete` (после `seed_starter_templates` дважды: 7 шаблонов, у каждого одна версия `is_starter=True`, `current_version` задана); `test_new_company_gets_starter_set` (через `create_company_with_defaults`); `test_backfill_seeds_existing_company_once`; `test_act_and_order_request_loops_render_all_rows` (в акте все позиции счёта, в заявке все грузы).
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement.** Тексты - краткие образцы на русском (структура реальных документов: стороны, предмет, цена, сроки, реквизиты, подписи); юридически значимый текст не изобретать сверх необходимого. **Step 4: Run** - PASS.
- [ ] **Step 5: Commit** `feat(documents): стартовый набор шаблонов и сидирование`.

---

### Task 9: Сервисы: версии, откат, выдача, сборка файла

**Files:**
- Create: `backend/apps/documents/services.py`
- Test: `backend/apps/documents/tests/test_services.py`

**Interfaces:**
- Consumes: `engine`, `context.build_context`, `next_number` (`apps.core.numbering.services`), `audit` (`apps.core.audit.services`), `pdf.convert_to_pdf` (Задача 10; в этой задаче вызывается через модуль и тестируется там).
- Produces:
  - `upload_version(template: DocumentTemplate, data: bytes, user) -> DocumentTemplateVersion` - `validate_upload`, новая версия (`number = max+1`), `sha256`, перевод `current_version`, аудит.
  - `reset_to_starter(template, user) -> DocumentTemplateVersion` - новая версия из `starter_bytes(template.kind, template.language)`, `is_starter=True`.
  - `issue_document(kind: str, *, user, client=None, order=None, trip=None, invoice=None, letter: dict | None = None, language: str | None = None) -> IssuedDocument` - `@transaction.atomic`; выбор шаблона (Global Constraints), проверки привязки и состояния (таблица спеки, раздел 4; блокировка источника `select_for_update`), номер (`next_number(kind)` для `NUMBERED_KINDS`, иначе номер заказа/счёта), `build_context`, запись журнала со снимком, аудит `create`. Ошибки: `template_missing`, `source_not_ready`, `letter_invalid`.
  - `render_issued(doc: IssuedDocument, fmt: str) -> tuple[bytes, str, str]` - `(content, content_type, filename)`; `docx` из версии шаблона и снимка; `pdf` через `pdf.convert_to_pdf`; имя файла `<kind>-<number>.<ext>` с безопасными символами.

- [ ] **Step 1: Write failing tests**: `test_upload_version_increments_and_switches_current` ; `test_upload_invalid_does_not_create_version` (после ошибки версий не прибавилось); `test_reset_to_starter_creates_new_starter_version`; `test_issue_order_request_uses_order_number_no_counter_spent` (счётчик нумерации не изменился); `test_issue_act_numbers_sequentially` (`АКТ-<год>-00001`, затем `00002`); `test_issue_act_requires_issued_invoice` (черновик и отменённый -> `source_not_ready`); `test_issue_carrier_order_requires_carrier`; `test_issue_requires_active_template` (отключённый шаблон -> `template_missing`); `test_language_fallback_to_ru` (компания `kk`, шаблонов `kk` нет -> берётся `ru`); `test_letter_validation` (пустая тема/текст, текст 20 001 символ -> `letter_invalid`); `test_snapshot_unchanged_after_order_edit_and_delete` (правка ставки и мягкое удаление заказа, `render_issued` docx даёт прежние значения); `test_old_document_keeps_old_template_version` (после новой версии шаблона выданный ранее собирается по старой); `test_concurrent_issue_unique_numbers` (два потока, `transaction=True, serialized_rollback=True`; разные номера); `test_rollback_does_not_burn_number` (исключение внутри транзакции после выдачи - следующий номер без пропуска); `test_filename_is_safe` (название с пробелами/кириллицей/слэшем не ломает имя).
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement** по сигнатурам; условия источников - одна таблица внутри модуля. **Step 4: Run** `python -m pytest apps/documents -q` - PASS.
- [ ] **Step 5: Commit** `feat(documents): выдача документов, версии шаблонов, сборка файла`.

---

### Task 10: Конвертация в PDF

**Files:**
- Create: `backend/apps/documents/pdf.py`
- Test: `backend/apps/documents/tests/test_pdf.py`

**Interfaces:**
- Produces: `pdf_available() -> bool` (`shutil.which("soffice")`); `convert_to_pdf(docx: bytes) -> bytes` - временный каталог, `soffice --headless --norestore --convert-to pdf --outdir <tmp> -env:UserInstallation=file://<tmp>/profile`, таймаут 60 с (`PDF_TIMEOUT_SECONDS`), эксклюзивная блокировка файла `fcntl.flock` в системном tmp (одна конвертация одновременно, ожидание до 30 с, иначе `pdf_unavailable`), результат читается в память, каталог удаляется; нет `soffice`, ненулевой код, нет выходного файла, таймаут -> `DocumentError("pdf_unavailable", ..., status_code=503)`.

- [ ] **Step 1: Write failing tests**: `test_pdf_available_reflects_binary` (monkeypatch `shutil.which`); `test_convert_produces_pdf` (пропуск `pytest.mark.skipif(not pdf_available())`: результат начинается с `%PDF`, содержит текст документа - проверка через простую подстроку/`pypdf` не требуется, достаточно сигнатуры и размера > 1 КБ); `test_missing_binary_raises_pdf_unavailable` (monkeypatch -> код `pdf_unavailable`, статус 503); `test_timeout_raises_pdf_unavailable` (monkeypatch `subprocess.run` с `TimeoutExpired`); `test_temp_dir_cleaned` (каталог не остаётся после успеха и после сбоя); `test_busy_lock_times_out` (удерживаемая блокировка -> `pdf_unavailable` без зависания, ожидание в тесте уменьшено настройкой `PDF_LOCK_WAIT_SECONDS`).
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement** через `subprocess.run(..., check=False, capture_output=True, timeout=...)`. **Step 4: Run** - PASS.
- [ ] **Step 5: Commit** `feat(documents): конвертация DOCX в PDF через LibreOffice`.

---

### Task 11: API шаблонов, журнала и capabilities

**Files:**
- Create: `backend/apps/documents/api/{__init__,serializers,templates,issued,capabilities}.py`
- Modify: `backend/config/urls.py` (роутер `documents/templates`, `documents/issued`; `path("api/documents/capabilities/", ...)`; `GET templates/placeholders/` объявить раньше `templates/{id}/`)
- Test: `backend/apps/documents/tests/test_api.py`

**Interfaces:**
- Consumes: `services.*`, `catalog.placeholders`, `pdf.pdf_available`, `permission_required`, `ModuleRequired("forwarding")`, `AuditedMixin` по образцу `apps/finance/api/*`.
- Produces (спека, раздел 7): `GET templates/` (в ответе `current_version {id, number, sha256, is_starter, uploaded_by, created_at}`, `versions_count`); `PATCH templates/{id}/` (`name`, `is_active`; включение шаблона, если уже есть активный того же вида и языка, -> 400); `POST templates/{id}/versions/` (multipart `file`); `GET templates/{id}/download/`; `POST templates/{id}/reset/`; `GET templates/placeholders/?kind=` (неизвестный вид -> 400); `GET issued/` (фильтры `kind`, `client`, `order`, `trip`, `invoice`, `date_from`, `date_to`, `search` по номеру); `GET issued/{id}/`; `POST issued/` (тело `{kind, client|order|trip|invoice, letter?, language?}`; лишний или недостающий источник для вида -> 400); `GET issued/{id}/download/?format=docx|pdf` (неверный формат -> 400); `GET capabilities/` -> `{"pdf_available": bool}`. Права: просмотр - `documents.view`; выдача - `documents.create` плюс доступ к источнику; версии/откат/PATCH - `documents.update`; отключение через PATCH `is_active=false` - `documents.delete`.

- [ ] **Step 1: Write failing tests** `test_api.py`: `test_templates_list_has_starter_set` ; `test_upload_version_and_download` (загрузка валидного docx -> 201, `current_version.number == 2`; скачивание отдаёт загруженные байты); `test_upload_invalid_is_400_with_code` (`template_invalid`, `template_too_large`); `test_reset_returns_starter`; `test_placeholders_endpoint` (имена из каталога; неизвестный вид -> 400); `test_issue_requires_exactly_one_source` ; `test_issue_each_kind_and_download_docx` (7 видов, `Content-Type` docx, имя файла в `Content-Disposition`); `test_download_pdf_unavailable_is_503_but_docx_ok` (monkeypatch `pdf_available`/`convert_to_pdf`); `test_capabilities_flag`; `test_permissions_matrix` (Менеджер выдаёт, но не загружает версию; Наблюдатель только читает; Механик 403 на всё; без `finance.view` нельзя выдать акт); `test_foreign_company_ids_rejected` (чужие client/order/trip/invoice -> 400/404, не 500); `test_company_isolation_list_download_template` ; `test_download_after_order_deleted` (приоритет 6 фокуса: 200 из снимка); `test_filters_and_search`; `test_audit_written_for_issue_and_version`; `test_rls_role_flow` (под `app_role()`: загрузить версию, выдать, скачать); `test_query_count_stable_for_list` (список из 30 записей - число запросов не растёт).
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement** (простые Serializer и функции представления, как в финансах; multipart через `MultiPartParser`; скачивание через `HttpResponse` с `Cache-Control: private, no-store`). **Step 4: Run** `python -m pytest apps/documents -q` и `python manage.py check_rls` - PASS.
- [ ] **Step 5: Commit** `feat(documents): API шаблонов, журнала выданных и capabilities`.

---

### Task 12: Образ сервера (LibreOffice, шрифты), сквозной бэкенд-тест, документация

**Files:**
- Modify: `deploy/Dockerfile.backend` (финальный слой: `apt-get install -y --no-install-recommends libreoffice-writer fonts-dejavu-core fonts-liberation2 fonts-noto-core` и очистка списков; только в финальном образе), `docs/ops/RUNBOOK.md` (раздел «Документы (этап 3B)»: образ тяжелее на ~0,4 ГБ, пересборка, `pdf_available`, шаблоны компании хранятся в БД и входят в бэкап, на демо Vercel PDF недоступен), `docs/ops/VERCEL.md` (строка в ограничениях демо)
- Create: `backend/apps/documents/tests/test_end_to_end.py`
- Test: `backend/apps/documents/tests/test_end_to_end.py`

**Interfaces:** без новых.

- [ ] **Step 1: Write the test** `test_full_flow`: компания -> клиент, заказ с двумя грузами -> счёт клиенту выставлен -> выдать `order_request`, `act`, `invoice_print` -> загрузить свою версию шаблона акта с изменённым текстом -> новый акт собирается по новой версии, старый (выданный ранее) по старой -> правка ставки заказа не меняет скачанный документ -> всё под `app_role()`.
- [ ] **Step 2: Run** `python -m pytest -q` (весь бэкенд, одним процессом, в фоне) - PASS; `ruff check .`; `python manage.py makemigrations --check --dry-run`; `python manage.py check_rls`.
- [ ] **Step 3: Docs** - добавить текст в RUNBOOK и VERCEL.md; в Dockerfile - команда установки (проверить `bash -n`-аналогом не нужно; сборка образа в этой среде не выполняется - пометить в RUNBOOK «не проверено: сборка образа с LibreOffice»).
- [ ] **Step 4: Commit** `feat(documents): образ с LibreOffice, сквозной тест, документация`.

---

### Task 13: Фронтенд: типы, API, хуки, права, меню, настройки шаблонов

**Files:**
- Create: `web/src/features/documents/{types.ts,api.ts,hooks.ts,TemplatesPage.tsx,TemplatesPage.test.tsx}`
- Modify: `web/src/layout/nav.ts` (пункт `documents` -> `/documents`, `documents.view`, `module: 'forwarding'`; в «Настройках» пункт `doctemplates` -> `/settings/document-templates`, `documents.view`), `web/src/app/router.tsx` (страницы `/documents` и `/settings/document-templates` в `PAGES`), `web/src/features/settings/roles/catalog.ts` (`SECTIONS` + `'documents'`), `web/src/test/permissions.ts` (раздел `documents`), `web/src/shared/api/errors.ts` (6 новых кодов в `FINANCE_CODES`-подобном наборе: сделать общий `KNOWN_CODES` с префиксами `errors.finance.*`/`errors.documents.*`), `web/src/shared/i18n/{ru,kk}.json` (`nav.documents`, `nav.doctemplates`, `roles.sections.documents`, `errors.documents.*`, `documents.*`), правки ожиданий в `RolesPage.test.tsx` (сетка 52, всего 54)
- Test: `web/src/features/documents/TemplatesPage.test.tsx`, `web/src/layout/nav.test.ts`

**Interfaces:**
- Produces: типы `DocumentKind`, `DocTemplate`, `DocTemplateVersion`, `IssuedDocument`, `Placeholder`; `api.ts`: `listTemplates`, `uploadTemplateVersion(id, file)`, `downloadTemplate(id)`, `resetTemplate(id)`, `patchTemplate(id, body)`, `listPlaceholders(kind)`, `listIssued(filters)`, `issueDocument(body)`, `downloadIssued(id, format)`, `getCapabilities()`; хуки `useTemplates`, `useUploadVersion`, `useResetTemplate`, `usePlaceholders`, `useIssued`, `useIssueDocument`, `useCapabilities`; страница «Шаблоны документов»: таблица (вид, название, язык, версия, активен), «Скачать текущий», «Загрузить новую версию» (input file `.docx`, ошибки сервера по коду), «Вернуть стартовую», «Метки» (окно со справочником меток вида), отключение/включение (право `documents.delete`/`update`).

- [ ] **Step 1: Write failing tests** `TemplatesPage.test.tsx`: список шаблонов с версией и меткой «стартовая»; загрузка файла вызывает `POST .../versions/` с `FormData` и показывает ошибку `template_invalid` на языке интерфейса; без права `documents.update` кнопки загрузки отключены; окно меток выводит имена из `GET templates/placeholders/?kind=`; скачивание вызывает download с именем файла; `nav.test.ts` - пункты видны только с `documents.view`.
- [ ] **Step 2: Run** `npx vitest run src/features/documents src/layout` - FAIL. **Step 3: Implement** по образцу `features/finance` (DataTable, Drawer/Dialog, WriteButton, `api.upload`, `saveBlob`, i18n). **Step 4: Run** `npx vitest run`, `npm run lint`, `npx tsc -b` - PASS.
- [ ] **Step 5: Commit** `feat(web): шаблоны документов, меню, права раздела documents`.

---

### Task 14: Фронтенд: журнал выданных документов и письмо на бланке

**Files:**
- Create: `web/src/features/documents/{DocumentsPage.tsx,LetterDrawer.tsx,DocumentsPage.test.tsx}`
- Modify: `web/src/shared/i18n/{ru,kk}.json` (ключи журнала и письма)

**Interfaces:**
- Consumes: хуки и API Задачи 13.
- Produces: страница `/documents`: таблица (дата, вид, номер, источник - ссылка на заказ/рейс/счёт/клиента, кто выдал, кнопки «DOCX» и «PDF» (скрыта, если `pdf_available=false`)), фильтры (вид, период, поиск по номеру; состояние хранится в адресе через `useUrlState`), кнопка «Письмо на бланке» (право `documents.create`) открывает форму (адресат, тема, текст) и выдаёт `letter`; после выдачи - диалог «Документ <номер> выдан» с кнопками скачивания (общий компонент `IssuedDialog` Задачи 15).

- [ ] **Step 1: Write failing tests**: список с номерами и ссылками на источники; кнопка PDF скрыта при `pdf_available=false`; скачивание DOCX/PDF вызывает нужный URL; форма письма отправляет `{kind:'letter', letter:{recipient,subject,body}}`, пустая тема/текст блокируют отправку, длинный текст (20 001) показывает ошибку; ошибка `template_missing` показана переводом; без `documents.create` кнопка письма отключена; фильтры уходят в запрос.
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement.** **Step 4: Run** `npx vitest run`, lint, tsc - PASS.
- [ ] **Step 5: Commit** `feat(web): журнал выданных документов и письмо на бланке`.

---

### Task 15: Фронтенд: кнопки выдачи в заказе, счёте, рейсе и карточке клиента

**Files:**
- Create: `web/src/features/documents/{IssueDocumentButton.tsx,IssuedDialog.tsx,IssueDocumentButton.test.tsx}`
- Modify: `web/src/features/orders/pages/OrderDetailPage.tsx` («Заявка клиента»), `web/src/features/finance/InvoiceDetailPage.tsx` («Счёт на оплату», «Акт» - только для выставленного счёта клиенту), страница/карточка рейса `web/src/features/trips/**` («Договор-заявка перевозчику» при наличии перевозчика, «CMR»), `web/src/features/parties/components/PartyDrawer.tsx` («Договор» при правке клиента), `web/src/shared/i18n/{ru,kk}.json`

**Interfaces:**
- Produces: `<IssueDocumentButton kind source label />` (`source: {client?: number; order?: number; trip?: number; invoice?: number}`): по нажатию `POST issued/`, затем `IssuedDialog` («Документ <номер> выдан», «Скачать DOCX», «Скачать PDF» - если `pdf_available`, «Закрыть»); кнопка отключена без `documents.create` (и скрыта без модуля `forwarding`); ошибки по коду (`template_missing`, `source_not_ready`) показываются в диалоге.

- [ ] **Step 1: Write failing tests**: нажатие выдаёт документ и открывает диалог с номером; DOCX/PDF скачиваются через `download`; без права кнопка отключена; `source_not_ready` показывает перевод; в счёте кнопки «Акт» нет у черновика и отменённого; в рейсе без перевозчика нет «Договор-заявка перевозчику»; повторное нажатие не создаёт второй документ, пока идёт запрос.
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement.** **Step 4: Run** `npx vitest run`, `npm run lint`, `npx tsc -b`, `npm run build` - PASS.
- [ ] **Step 5: Commit** `feat(web): кнопки выдачи документов в заказе, счёте, рейсе и клиенте`.

---

### Task 16: Реквизиты контрагента в интерфейсе

**Files:**
- Modify: `web/src/features/parties/components/PartyDrawer.tsx`, `web/src/features/parties/types.ts`, `web/src/shared/i18n/{ru,kk}.json`
- Test: `web/src/features/clients/ClientsPage.test.tsx`, `web/src/features/carriers/CarriersPage.test.tsx` (добавить случаи)

**Interfaces:**
- Consumes: поля `address`, `bank`, `iban` API (Задача 2).
- Produces: в карточке клиента и перевозчика три необязательных поля «Адрес», «Банк», «IBAN»; значения уходят в `POST/PATCH`, ошибки сервера (IBAN длиннее 34) показываются у поля.

- [ ] **Step 1: Write failing tests**: поля видны при редактировании и заполняются из ответа; создание отправляет `address/bank/iban` (пустые - пустыми строками); ошибка 400 по `iban` отображается у поля.
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement.** **Step 4: Run** `npx vitest run`, lint, tsc - PASS.
- [ ] **Step 5: Commit** `feat(web): адрес, банк и IBAN в карточке контрагента`.

---

## Self-review (при составлении плана)

- **Покрытие спеки:** модели (раздел 3) - Задача 4; виды и привязки (4) - Задачи 1, 9; контекст (5) - Задачи 5, 7; правила (6): права - 1, 11; загрузка и песочница - 6; выдача - 9; PDF - 10; язык - 9; API (7) - 11; интерфейс (8) - 13-16; тесты (9) - в тестах каждой задачи; риски (10) - Задача 12 (образ) и Review Focus.
- **Отклонения от спеки (решения плана):** (1) поля адреса, банка и IBAN контрагента добавлены отдельной задачей (2 и 16): в карточках их не было, а спека (раздел 5) их подразумевает; (2) выбор языка шаблона с возвратом к `ru`, если для языка компании шаблона нет (иначе компания с казахским интерфейсом не смогла бы выдавать документы); (3) PDF-ответ при сбое - HTTP 503 с кодом `pdf_unavailable`.
- **Согласованность имён:** `DocumentError`, `validate_upload`, `render_docx`, `build_context`, `issue_document`, `render_issued`, `convert_to_pdf`, `pdf_available`, `starter_bytes`, `seed_starter_templates`, `placeholders`, `sample_context` совпадают во всех задачах.
- **Не вошло по спеке:** отправка письмом (этап 5), казахские стартовые шаблоны, картинки-метки, электронная подпись, редактор шаблонов, MinIO.
