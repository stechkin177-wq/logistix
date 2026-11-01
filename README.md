# Logistix

SaaS для экспедиторов и перевозчиков Казахстана (Django + React): заказы, рейсы,
консолидация, клиенты и перевозчики, прибыль. Спецификация и план: `docs/superpowers/`.

## Структура
- `backend/` - Django + DRF (`config/` настройки, `apps/` приложения)
- `web/` - фронтенд на React (появится в Task 15)
- `deploy/` - SQL инициализации БД (роль `logistix_app`)
- `docker-compose.yml` - PostgreSQL 16 и Redis 7
- `.github/workflows/ci.yml` - CI (backend, web)

## Запуск для разработки
```bash
docker compose up -d                      # postgres + redis
python3 -m venv ~/.venv-logistix          # Python 3.12+
cp .env.example .env                      # переменные окружения
set -a; . ./.env; set +a
cd backend
~/.venv-logistix/bin/pip install -e ".[dev]"
~/.venv-logistix/bin/python manage.py migrate
~/.venv-logistix/bin/python manage.py runserver
```
Проверка: `GET http://localhost:8000/api/health/` -> `{"status": "ok"}`.

## Тесты и линтер
Тесты идут на реальном PostgreSQL (без SQLite):
```bash
cd backend && ~/.venv-logistix/bin/pytest -q && ~/.venv-logistix/bin/ruff check .
```

## База данных и RLS
Изоляция компаний двухуровневая: менеджер `TenantModel.objects` фильтрует по текущей
компании, а PostgreSQL Row-Level Security (политика `tenant_isolation`,
`apps/core/rls.py`) не показывает и не даёт записать строки другой компании, даже при
прямом SQL. Текущая компания передаётся в БД параметром сессии `app.company_id`;
без него таблицы компаний пусты.

- `DATABASE_URL` - единственная настройка подключения.
- Миграции можно выполнять ролью-владельцем таблиц (`logistix`).
- Приложение подключается ролью `NOSUPERUSER NOBYPASSRLS` (`logistix_app`, создаётся
  `deploy/db-init.sql` в docker-compose и CI). `FORCE ROW LEVEL SECURITY` подчиняет
  политике и владельца, но суперпользователь и роль с `BYPASSRLS` обходят RLS всегда:
  в продакшене приложение под суперпользователем не запускать.
- `python manage.py check_rls` завершается с ошибкой, если роль подключения -
  суперпользователь или `BYPASSRLS`, либо у таблицы компании нет RLS. Запускать при
  деплое с продакшен-`DATABASE_URL`.
- В разработке и тестах Django подключается суперпользователем `logistix` (RLS не
  действует); тесты RLS переключаются на `logistix_app` через `SET LOCAL ROLE`.
- Новая модель `TenantModel` обязана получить в своей миграции
  `apps.core.rls.EnableRLS("app.Model")`, иначе упадёт тест
  `test_every_tenant_table_has_rls`. Таблицы `Company`, `User`, `Membership`,
  `Subscription`, `Plan`, `CompanyBranding` без RLS: они читаются до выбора компании (вход,
  аутентификация, публичный `GET /api/branding/?host=` для экрана входа).

## Переменные окружения
См. `.env.example`: `DJANGO_SECRET_KEY` (обязателен при `DJANGO_DEBUG=false`),
`DJANGO_DEBUG` (по умолчанию false), `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`,
`REDIS_URL`, `CORS_ALLOWED_ORIGINS`, `JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS`,
`MEDIA_ROOT`/`MEDIA_URL` (логотипы компаний на локальном диске; S3/MinIO - этап 5),
`BRANDING_THROTTLE_RATE` (лимит публичного `/api/branding/`, по умолчанию `60/min`).
