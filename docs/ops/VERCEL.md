# Временный демо-запуск на бесплатном Vercel

Цель: показать Logistix на бесплатных сервисах (Vercel Hobby + Neon Free) ДО покупки домена и VPS.
Это не продакшен и не замена [RUNBOOK](RUNBOOK.md) (hoster.kz).

## Правило №1: только вымышленные данные

- Тариф Vercel **Hobby предназначен для некоммерческого личного использования** (условия Vercel;
  проверьте актуальную редакцию). Работа с настоящими клиентами - коммерческое использование.
- База и функции находятся **за пределами Казахстана** (Neon и Vercel, регион Frankfurt), надёжных
  бэкапов нет: это противоречит требованию о размещении персональных данных в РК.
- Поэтому в демо - **только выдуманные компании, клиенты, телефоны и e-mail**. Реальные данные не вносить.

## Архитектура

```
Браузер ──► Vercel проект "web" (статика Vite, https://<web>.vercel.app)
               │  /api/*  -- внешний rewrite (прокси) -->  Vercel проект "api" (Django, WSGI-функция, fra1)
               │  /*      -- SPA-фолбэк на /index.html                    │
               └─ заголовки безопасности (CSP и др.)                      ▼
                                                          Neon Postgres (Frankfurt), ПРЯМОЕ подключение,
                                                          роль logistix_app (NOSUPERUSER NOBYPASSRLS)
```

Браузер общается только с origin проекта `web`. `/media/*` не обслуживается: на serverless нет
постоянного диска, загруженные логотипы не сохраняются.

## Что подтверждено документацией Vercel, а что нет

Подтверждено (поиск по документации Vercel при подготовке):
- Django-приложение определяется по `WSGI_APPLICATION` в настройках (и/или `[tool.vercel] entrypoint`
  в `pyproject.toml`), превращается в ОДНУ функцию; в `vercel.json` ключ `functions` задаётся по
  файлу точки входа относительно Root Directory (у нас `config/wsgi.py`).
- Ключи `regions`, `functions.<файл>.maxDuration`, `functions.<файл>.excludeFiles`, внешние `rewrites`
  на другой origin (`https://.../:path*`), `headers`; на Hobby можно выбрать один регион.
- Зависимости Python берутся из `requirements.txt` или `pyproject.toml`; лимит бандла 500 МБ.

**НЕ подтверждено (проверьте сами):** лимиты тарифа Hobby (максимальная `maxDuration`, размер тела
запроса, холодный старт) - выбрано консервативное `maxDuration: 30`; какой из двух файлов
зависимостей (`requirements.txt` или `pyproject.toml`) Vercel использует, если есть оба
(в обоих рантайм-зависимости совпадают, различается только `gunicorn`, который не мешает);
доступность Root Directory + внешнего rewrite именно на вашем плане; передача `X-Forwarded-Proto`
в API через rewrite (иначе `SECURE_SSL_REDIRECT` даст цикл редиректов - см. «Если что-то не так»).

## Шаги

### 1. Neon (Frankfurt)

1. neon.tech: создайте проект, регион **AWS Europe (Frankfurt)**.
2. Connection string: переключатель **Pooled connection ВЫКЛЮЧЕН** - нужна **прямая** строка
   (хост вида `ep-...eu-central-1.aws.neon.tech`). Строку с `-pooler` в хосте **никогда** не
   используйте: транзакционный PgBouncer смешивает сессии, а RLS держит `app.company_id` в сессии -
   это утечка данных между компаниями. Приложение с такой строкой не запустится (защита в
   `config/dbguard.py`).

### 2. Роли и права

`deploy/db-init.sql` создаёт роль `logistix_app` и выдаёт права; имя БД и владельца берёт из
подключения. Выполните ОТ ВЛАДЕЛЬЦА (та же роль, что потом выполнит миграции), на вашем компьютере:

```bash
export APP_DB_PASSWORD="$(openssl rand -hex 24)"   # сохраните это значение
psql "postgresql://<owner>:<owner-password>@<direct-host>/<db>?sslmode=require" -f deploy/db-init.sql
```

Нужен `psql` 15+ (используется `\getenv`). Затем соберите строку приложения:
`postgresql://logistix_app:<APP_DB_PASSWORD>@<direct-host>/<db>?sslmode=require`.

### 3. Миграции (от владельца, НЕ из функции)

```bash
cd backend
DATABASE_URL='<owner direct url>' DJANGO_DEBUG=true DJANGO_SERVERLESS=true \
  /path/to/venv/bin/python manage.py migrate
```

`DJANGO_SERVERLESS=true` включает и в этих командах запрет пулера. Сборка Vercel миграции и
`collectstatic` не запускает.

### 4. Проверка RLS - обязательно

```bash
DATABASE_URL='<APP role direct url>' DJANGO_DEBUG=true DJANGO_SERVERLESS=true \
  /path/to/venv/bin/python manage.py check_rls
```

Должно завершиться кодом 0 («RLS в порядке»). Если у провайдера роль приложения получается
суперпользователем/с BYPASSRLS и проверка падает - не продолжайте: перейдите на Supabase
(session pooler, порт 5432, `...pooler.supabase.com`) или остановитесь.

### 5. Первая компания (вымышленная)

```bash
DEMO_OWNER_PASSWORD='<придумайте>' DATABASE_URL='<owner direct url>' DJANGO_DEBUG=true \
  python manage.py bootstrap_company --name "Демо Логистик" --owner-login demo@example.com \
  --owner-name "Демо Владелец" --password-env DEMO_OWNER_PASSWORD
```

### 6. Два проекта Vercel из одного репозитория

Создавайте проекты вручную в Vercel (этот репозиторий ничего не создаёт). Сначала переменные,
потом первый деплой. Хосты ниже заменяйте на реальные.

**Проект `logistix-api`:** Root Directory `backend`, Framework Preset Django/Python (определяется
автоматически), Function Region `fra1` (также в `backend/vercel.json`). Build Command не задавать.
Переменные (пример значений: `backend/.env.vercel.example`):

| Переменная | Значение | Секрет |
|---|---|---|
| `DJANGO_SECRET_KEY` | 64+ случайных символов | да |
| `DATABASE_URL` | прямая строка роли `logistix_app` из шага 2 | да |
| `DJANGO_DEBUG` | `false` | |
| `DJANGO_SERVERLESS` | `true` | |
| `DATABASE_SSL_REQUIRE` | `true` | |
| `DATABASE_CONN_MAX_AGE` | `0` | |
| `DJANGO_ALLOWED_HOSTS` | `logistix-api.vercel.app,<web-host>` (без `*`) | |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://<web-host>` | |
| `CORS_ALLOWED_ORIGINS` | `https://<web-host>` | |
| `DJANGO_BEHIND_TLS_PROXY` | `true` | |
| `TRUST_PROXY_HEADERS` | `false` (IP, который видит API, - инфраструктура Vercel, не пользователь) | |
| `DJANGO_ADMIN_ENABLED` | `false` | |
| `THROTTLE_LOGIN` | `10/minute` (по умолчанию) | |
| `SENTRY_DSN`, `REDIS_URL` | не задавать | |

С внешним rewrite API видит хост назначения (`logistix-api.vercel.app`), поэтому он обязан быть в
`DJANGO_ALLOWED_HOSTS`.

**Проект `logistix-web`:** Root Directory `web`, preset Vite, Install `npm ci`, Build `npm run build`,
Output `dist`. Переменные окружения не нужны. Адрес API - в `web/vercel.json`
(`rewrites[0].destination`, по умолчанию `https://logistix-api.vercel.app/api/:path*`).
**Замените, если имя проекта `logistix-api` занято** (Vercel даст другой адрес) - и закоммитьте.

HSTS мы не задаём: HTTPS на `*.vercel.app` обеспечивает Vercel. Заголовки CSP, nosniff,
X-Frame-Options, Referrer-Policy, Permissions-Policy заданы в `web/vercel.json` (как в nginx).

### 7. Проверка после первого деплоя

```bash
SMOKE_SKIP_WEB=0 SMOKE_CHECK_HEADERS=1 SMOKE_TIMEOUT=30 deploy/smoke.sh https://<web-host>.vercel.app
curl -si https://<web-host>.vercel.app/api/health/ | head -20
curl -si https://<web-host>.vercel.app/orders | head -20      # 200, HTML SPA
curl -sI https://<web-host>.vercel.app/ | grep -i content-security
```

Первый запрос может быть медленным (холодный старт функции, пробуждение Neon) - поэтому таймаут 30.
Затем войдите в браузере вымышленным владельцем и откройте консоль: нет ли нарушений CSP.

### Если что-то не так

- Бесконечные редиректы / 301 на `/api/*`: API не получает `X-Forwarded-Proto: https` через
  rewrite. Проверьте заголовки; временной "обходной" настройкой НЕ делайте отключение проверок
  безопасности без осознанного решения (`DJANGO_BEHIND_TLS_PROXY=false` ослабляет cookie/редирект).
- 400 `DisallowedHost`: добавьте хост в `DJANGO_ALLOWED_HOSTS`.
- 500 при старте с текстом про пулер: исправьте `DATABASE_URL` (шаг 1).

## Известные ограничения

- Холодные старты функции и автоусыпление Neon (первые секунды после простоя).
- Лимит времени одной функции (`maxDuration: 30`); тяжёлые отчёты/выгрузки могут не уложиться.
- Логотипы компаний не сохраняются (нет диска, `/media` не раздаётся).
- Счётчики throttle - на экземпляр функции (нет Redis; общий Redis можно подключить, например
  Upstash, через `REDIS_URL` - по желанию). Защита входа - лимит на логин (`THROTTLE_LOGIN`), но
  экземпляров может быть несколько, поэтому фактический предел выше.
- Нет edge-лимитов nginx (`limit_req`), нет Celery/beat/cron.
- Бесплатная БД может приостанавливаться/удаляться при неактивности и имеет лимиты по размеру и
  времени вычислений - **сверьте актуальные условия Neon и Vercel**.

## Ротация и сворачивание

- Раздали демо-доступ - после показа смените пароли владельца в приложении и пароль роли
  `logistix_app` (`ALTER ROLE ... PASSWORD`), обновите `DATABASE_URL` в Vercel, передеплойте.
- Заканчивая демо: удалите проекты Vercel и проект Neon, отзовите ключи. Переход на hoster.kz -
  по [RUNBOOK](RUNBOOK.md).

## Что НЕ проверено при подготовке

Не выполнялось (среда без доступа к Vercel/Neon): реальная сборка и деплой на Vercel; поведение
ролей и `check_rls` на Neon; проксирование внешним rewrite (заголовки, `X-Forwarded-Proto`, хост);
CSP в браузере (в т.ч. шрифты/изображения SPA); лимиты Hobby из раздела выше; приоритет
`requirements.txt` над `pyproject.toml`. Проверено автотестами: разбор URL пулера, настройки
serverless, JSON-рендерер, троттлинг входа, структура обоих `vercel.json`, синхронность
`requirements.txt`.
