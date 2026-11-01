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
   это утечка данных между компаниями.
3. **Защита в `config/dbguard.py` - эвристика, а не гарантия.** Она распознаёт только: хосты Neon с
   `-pooler.`, порты 6543 (Supabase) и 6432 (PgBouncer по умолчанию), `pgbouncer=true`, ключи
   `host`/`hostaddr` в строке; неразбираемые строки (несколько хостов, неверный порт) отклоняются.
   **Другие пулеры (на нестандартных портах и хостах) НЕ распознаются.** Ответственность за прямую
   строку - на владельце.

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
DEMO_OWNER_PASSWORD='<придумайте>' DATABASE_URL='<owner direct url>' DJANGO_DEBUG=true DJANGO_SERVERLESS=true \
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
| `DJANGO_BEHIND_TLS_PROXY` | `true` (cookie только по https, доверие `X-Forwarded-Proto`) | |
| `DJANGO_SSL_REDIRECT` | `false` - см. пояснение ниже | |
| `MEDIA_ROOT` | `/tmp/media` (на serverless доступна запись только в `/tmp`) | |
| `TRUST_PROXY_HEADERS` | `false` (IP, который видит API, - инфраструктура Vercel, не пользователь) | |
| `DJANGO_ADMIN_ENABLED` | `false` | |
| `THROTTLE_LOGIN` | `10/minute` (по умолчанию) | |
| `SENTRY_DSN`, `REDIS_URL` | не задавать | |

**Почему `DJANGO_SSL_REDIRECT=false` и почему это допустимо ТОЛЬКО для демо.** Если Vercel не
передаёт `X-Forwarded-Proto: https` через внешний rewrite, Django видит каждый запрос как http и
отвечает 301 на https-адрес - получается бесконечный цикл на всех `/api/*` (исключение для
`/api/health/` скрывает цикл именно на health). Для демо редирект отключаем: TLS завершает Vercel,
`web` отдаётся только по HTTPS, а адрес api на `*.vercel.app` тоже только HTTPS. На продакшене с
собственным прокси так делать нельзя (там флаг не задаётся, по умолчанию равен
`DJANGO_BEHIND_TLS_PROXY`).

С внешним rewrite API видит хост назначения (`logistix-api.vercel.app`), поэтому он обязан быть в
`DJANGO_ALLOWED_HOSTS`.

**Проект `logistix-web`:** Root Directory `web`, preset Vite, Install `npm ci`, Build `npm run build`,
Output `dist`. Переменные окружения не нужны. Адрес API - в `web/vercel.json`
(`rewrites[0].destination`, по умолчанию `https://logistix-api.vercel.app/api/:path*`).
**Замените, если имя проекта `logistix-api` занято** (Vercel даст другой адрес) - и закоммитьте.

HSTS мы не задаём: HTTPS на `*.vercel.app` обеспечивает Vercel. Заголовки CSP, nosniff,
X-Frame-Options, Referrer-Policy, Permissions-Policy заданы в `web/vercel.json` (как в nginx).

### 6a. Вариант без своего компьютера: миграции из сборки Vercel (только Supabase)

Если до базы нет сети (например, работаете из облачной среды), миграции и первую компанию можно
выполнить из СБОРКИ временного проекта Vercel скриптом `backend/scripts/vercel_bootstrap.py`
(Root Directory `backend`, Build Command `pip install -r requirements.txt && python scripts/vercel_bootstrap.py`).
Скрипт сам подбирает рабочий адрес session-пулера Supabase (`aws-0`/`aws-1`, порт 5432, затем прямой хост),
запускает `migrate` под ролью `logistix_owner`, `check_rls` под `logistix_app` (сборка падает, если проверка
не пройдена) и `bootstrap_company`. Переменные временного проекта (все секретные - типа sensitive):
`SB_REF`, `SB_REGION`, `OWNER_PW`, `APP_PW`, `DEMO_OWNER_LOGIN`, `DEMO_OWNER_PW` (и по желанию
`DEMO_COMPANY_NAME`, `DEMO_OWNER_NAME`). Секреты в логи не попадают, печатается только выбранный хост.
После успешного запуска **временный проект нужно удалить** (в нём лежат пароли роли-владельца).

Перед первой миграцией на Supabase обязательно закройте публичный REST (Data API): отзовите право
`USAGE` на схему `public` у `PUBLIC`, `anon` и `authenticated` (иначе таблицы без RLS, например с
хэшами паролей, были бы доступны по публичному ключу проекта) и создайте роли `logistix_owner`
(владелец, `NOBYPASSRLS`) и `logistix_app` (`NOBYPASSRLS`) с `ALTER DEFAULT PRIVILEGES FOR ROLE
logistix_owner ... GRANT ... TO logistix_app`.

### 7. Проверка после первого деплоя

```bash
SMOKE_SKIP_WEB=0 SMOKE_CHECK_HEADERS=1 SMOKE_TIMEOUT=30 deploy/smoke.sh https://<web-host>.vercel.app
curl -si https://<web-host>.vercel.app/api/health/ | head -5          # ОБЯЗАТЕЛЬНО 200, не 301
curl -si -X POST https://<web-host>.vercel.app/api/auth/login/ \
  -H 'Content-Type: application/json' -d '{"login":"x","password":"y"}' | head -5   # 401 или 429
curl -si https://<web-host>.vercel.app/orders | head -20      # 200, HTML SPA
curl -sI https://<web-host>.vercel.app/ | grep -i content-security
```

POST на логин - настоящая проверка: исключение для `/api/health/` скрывает цикл редиректов именно на
health. Ожидается 401 (или 400/429), **не 301/308**. Если всё же 301 - убедитесь, что в проекте api
задано `DJANGO_SSL_REDIRECT=false` и выполнен передеплой (переменные применяются только к новым
деплоям); если после этого 301 остаётся - остановитесь и сообщите разработчику.

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
- Логотипы: загрузка может «пройти успешно» (запись в `/tmp/media`), но файл пропадёт при смене
  экземпляра функции, а `/media` не раздаётся. На логотипы в демо не рассчитывайте.
- Счётчики throttle - на экземпляр функции (нет Redis; общий Redis можно подключить, например
  Upstash, через `REDIS_URL` - по желанию). Защита входа - лимит на логин (`THROTTLE_LOGIN`):
  любой, кто знает чужой логин, может блокировать его вход на минуту за раз; разные логины между
  собой не ограничены; счётчик на экземпляр обходится параллельными/новыми (холодными) экземплярами,
  поэтому фактический предел выше. Это не защита от целенаправленного перебора.
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
