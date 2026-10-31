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

## Переменные окружения
См. `.env.example`: `DJANGO_SECRET_KEY` (обязателен при `DJANGO_DEBUG=false`),
`DJANGO_DEBUG` (по умолчанию false), `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`,
`REDIS_URL`, `CORS_ALLOWED_ORIGINS`, `JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS`.
