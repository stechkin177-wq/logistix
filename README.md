# Logistix

SaaS для экспедиторов и перевозчиков Казахстана (Django + React): заказы, рейсы,
консолидация, клиенты и перевозчики, прибыль. Спецификация и план: `docs/superpowers/`.

## Структура
- `backend/` - Django + DRF (`config/` настройки, `apps/` приложения)
- `web/` - фронтенд: React 19 + TypeScript + Vite + Tailwind (см. `web/README.md`)
- `deploy/` - продакшен: Dockerfile, `docker-compose.prod.yml`, nginx, бэкап/восстановление, SQL инициализации БД (роль `logistix_app`)
- `docs/ops/RUNBOOK.md` - **регламент эксплуатации и деплоя (hoster.kz)**
- `docker-compose.yml` - PostgreSQL 16 и Redis 7 для разработки
- `.github/workflows/` - CI (`ci.yml`) и деплой (`deploy.yml`)

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

## Фронтенд
```bash
cd web && npm ci && npm run dev    # http://localhost:5173, /api и /media идут на 127.0.0.1:8000
npm run typecheck && npm run lint && npm test && npm run build
```

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
`REDIS_URL` в продакшене ОБЯЗАТЕЛЕН: без него кэш - LocMem на процесс, и счётчики throttle
(публичный `/api/branding/`) не общие между воркерами; ключ throttle - IP по `TRUST_PROXY_HEADERS`,
`BRANDING_THROTTLE_RATE` (лимит публичного `/api/branding/`, по умолчанию `60/min`).

### Продакшен
`DJANGO_ALLOWED_HOSTS` (в продакшене задаётся явно), `DJANGO_CSRF_TRUSTED_ORIGINS`,
`DJANGO_BEHIND_TLS_PROXY` (доверять `X-Forwarded-Proto`, secure-cookie, редирект на https),
`DJANGO_ADMIN_ENABLED` (по умолчанию `true`; в продакшене `false`), `DJANGO_HSTS_SECONDS` и др.,
`SENTRY_DSN`/`SENTRY_ENVIRONMENT`/`SENTRY_TRACES_SAMPLE_RATE`. Полный список с пояснениями -
`deploy/.env.prod.example`. **Sentry:** DSN должен указывать на собственный/казахстанский Sentry
либо быть пустым (резидентность данных); персональные данные и тела запросов не отправляются.

Создание первой компании: `python manage.py bootstrap_company --name ... --owner-login ... --password-env VAR`.
Деплой, TLS, бэкапы, откат и чек-листы: [docs/ops/RUNBOOK.md](docs/ops/RUNBOOK.md).
