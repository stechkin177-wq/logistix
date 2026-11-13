# Регламент эксплуатации Logistix (hoster.kz)

Стек: Docker Compose на VPS в Казахстане. Сервисы: `nginx` (прокси, SPA, статика, медиа, TLS),
`backend` (gunicorn), `migrate` (одноразовый), `worker`/`beat` (Celery), `postgres:16`, `redis:7`.
Временный демо-запуск на бесплатном Vercel (только вымышленные данные): [VERCEL.md](VERCEL.md).
Поведение продакшена (`DJANGO_DEBUG=false`): (а) `DATABASE_URL`, похожий на транзакционный пулер
(Neon `-pooler`, порты 6543/6432, `pgbouncer=true`), отклоняется при старте, пока не задано
`DATABASE_POOLER_OK=true` - RLS держит `app.company_id` в сессии, транзакционный пулер смешал бы
компании (разрешайте только для пулера в режиме SESSION); (б) API отдаёт только JSON (без BrowsableAPI).
Наружу открыты только порты 80/443 (публикует nginx). Все файлы: каталог `deploy/`.

> **Что НЕ проверялось при подготовке (среда разработки без Docker и nginx).** См. раздел
> [Известные ограничения](#известные-ограничения-и-что-не-проверено). Первый реальный запуск образов
> и nginx произойдёт на сервере: пройдите «Первый деплой» вдумчиво и держите открытыми логи.

## 1. Требования к серверу

- ОС: Ubuntu 22.04/24.04 LTS (или Debian 12), 2 vCPU, 4 ГБ RAM, 40+ ГБ SSD (под БД, медиа и бэкапы).
- Docker Engine и плагин compose v2:
  ```bash
  curl -fsSL https://get.docker.com | sh        # или пакеты из репозитория Docker
  docker compose version                          # должен отвечать v2.x
  ```
- Пользователь для деплоя без root: `adduser deploy && usermod -aG docker deploy` (группа `docker`
  равна root-доступу: ключ этого пользователя храните как секрет). Вход по SSH только по ключу,
  `PasswordAuthentication no`, `PermitRootLogin no`.
- Файрвол пропускает только 22/80/443 (порт 22 по возможности - только с адресов администраторов):
  ```bash
  ufw default deny incoming && ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
  ```
  Docker сам добавляет правила iptables для опубликованных портов в обход ufw: поэтому в compose наружу
  опубликованы ТОЛЬКО 80/443 (postgres, redis, backend порты не публикуют). Не добавляйте `ports:` к ним.
- Время: `timedatectl set-ntp true`; часовой пояс сервера `Asia/Almaty` (приложение само работает в нём).
- **Локаль БД (обязательно).** База PostgreSQL ДОЛЖНА быть в UTF-8 с локалью, знающей кириллицу и
  казахский (`C.UTF-8` либо `ru_RU.UTF-8`/ICU `ru-RU`): от неё зависит регистронезависимый поиск `q` по
  клиентам и перевозчикам. Compose создаёт кластер с `--encoding=UTF8 --locale=C.UTF-8 --locale-provider=icu
  --icu-locale=ru-RU` (`POSTGRES_INITDB_ARGS`). Проверка после старта:
  ```bash
  ./deploy/dc.sh exec postgres \
    psql -U logistix -d logistix -c "SELECT datname, pg_encoding_to_char(encoding), datcollate, daticulocale FROM pg_database WHERE datname='logistix'"
  ```
  Ожидается `UTF8`, `C.UTF-8`, `ru-RU`. Если БД восстанавливаете в иной кластер - создавайте её с
  `ENCODING 'UTF8'` и той же локалью (`restore.sh` создаёт `LOCALE 'C.UTF-8'`, см. `RESTORE_CREATE_DB_OPTS`).
  Поиск использует сканирование таблицы компании (индекса под `ILIKE` нет); при росте данных - `pg_trgm`.

## 2. DNS

A-запись (и AAAA, если есть IPv6) `app.example.kz` на IP сервера. Для поддоменов компаний - wildcard
`*.example.kz`. Пользовательские домены компаний подключаются на этапе 5 (требуют: запись в
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS` и свой сертификат).

## 3. TLS

nginx ждёт сертификат в `${LETSENCRYPT_DIR}/live/logistix/{fullchain,privkey}.pem` (по умолчанию
`/etc/letsencrypt`, монтируется в контейнер read-only). Без файлов nginx НЕ стартует, поэтому сертификат
получают ДО первого `up`.

**Let's Encrypt (certbot), порт 80 свободен:**
```bash
sudo apt install -y certbot
sudo certbot certonly --standalone --cert-name logistix -d app.example.kz
```
**Обновление** (certbot создаёт таймер сам; нужны хуки, потому что порт 80 занят nginx):
```bash
sudo tee /etc/letsencrypt/renewal-hooks/pre/logistix-stop.sh >/dev/null <<'H'
#!/bin/sh
/opt/logistix/deploy/dc.sh stop nginx
H
sudo tee /etc/letsencrypt/renewal-hooks/post/logistix-start.sh >/dev/null <<'H'
#!/bin/sh
/opt/logistix/deploy/dc.sh start nginx
H
sudo chmod +x /etc/letsencrypt/renewal-hooks/{pre,post}/logistix-*.sh
sudo certbot renew --dry-run
```
(Минута простоя раз в ~60 дней. Альтернатива без простоя: nginx уже отдаёт `/.well-known/acme-challenge/`
из тома `certbot-webroot`; после первого запуска стека можно перейти на
`certbot certonly --webroot -w <путь тома certbot-webroot> --cert-name logistix -d ...` и использовать
`--deploy-hook "/opt/logistix/deploy/dc.sh exec nginx nginx -s reload"`. Не проверено.)

**Сертификат hoster.kz / иного удостоверяющего центра:** положите цепочку и ключ в
`/etc/letsencrypt/live/logistix/fullchain.pem` и `privkey.pem` (права ключа 600), перезагрузите nginx:
`./deploy/dc.sh exec nginx nginx -s reload`.

**HSTS** — см. раздел «HSTS: когда и как включать» ниже; по умолчанию выключен.

## 4. Первый деплой

1. Под пользователем `deploy`:
   ```bash
   sudo mkdir -p /opt/logistix && sudo chown deploy: /opt/logistix
   git clone https://github.com/<владелец>/logistix.git /opt/logistix && cd /opt/logistix
   ```
2. Окружение. **`.env.prod` создаётся на сервере вручную и в GitHub не хранится** (деплой-workflow его не
   трогает; `deploy/.env.prod` в `.gitignore`):
   ```bash
   cp deploy/.env.prod.example deploy/.env.prod && chmod 600 deploy/.env.prod
   # пароли: openssl rand -hex 24 ; ключ Django: python3 -c "import secrets; print(secrets.token_urlsafe(64))"
   $EDITOR deploy/.env.prod   # заменить ВСЕ dummy-значения, домен, BACKEND_IMAGE/WEB_IMAGE (ghcr.io/<владелец>/...)
   ```
   `POSTGRES_PASSWORD` (владелец, миграции/бэкапы) и `APP_DB_PASSWORD` (роль приложения) обязательно разные
   и НЕ равны паролю разработки `logistix_app`. Роль `logistix_app` создаётся `deploy/db-init.sql` при первой
   инициализации тома с паролем `APP_DB_PASSWORD`. Менять пароли после инициализации - см. раздел 9.
3. Сертификат (раздел 3).
4. Вход в реестр (если пакеты приватные; токен PAT с `read:packages`):
   `echo "$TOKEN" | docker login ghcr.io -u <пользователь> --password-stdin`.
5. Запуск (нужные образы уже собраны CI; для первого запуска без CI - `./deploy/dc.sh build` (после release.sh с тегом или с готовым `deploy/.image_tag.env`)):
   ```bash
   cd /opt/logistix
   # ПРОДАКШЕН: явный релизный тег (git-тег vX.Y.Z уже собран workflow), НИКОГДА не staging
   ./deploy/release.sh v1.0.0           # git-ref = тег v1.0.0 (выводится из тега)
   # СТЕНД (staging): тег конкретного коммита, собранного из main, например
   ./deploy/release.sh sha-1a2b3c4     # git-ref = коммит 1a2b3c4 (выводится из тега)
   ./deploy/dc.sh ps -a     # migrate: Exited (0)
   ```
   `release.sh` пишет тег в `deploy/.image_tag.env` (права 600, не в git) - это ЕДИНСТВЕННЫЙ источник тега:
   `release.sh` и обёртка `./deploy/dc.sh` (= `docker compose` с `--env-file .env.prod --env-file .image_tag.env`)
   читают его, а в `.env.prod` IMAGE_TAG не задаётся, и compose без тега не запускается. Не вызывайте
   `docker compose` напрямую без обоих файлов. Откат тега при сбое выкладки делает сам скрипт.
   `migrate` выполняет `migrate` под владельцем БД, собирает статику в общий том и запускает `check_rls`
   под ролью приложения. При ошибке `backend`/`worker`/`beat` не стартуют; смотрите
   `./deploy/dc.sh logs migrate`.
6. Первая компания и владелец (пароль - из переменной окружения или интерактивно, не в аргументах):
   ```bash
   read -rs OWNER_PW && export OWNER_PW
   ./deploy/dc.sh exec -e OWNER_PW backend python manage.py bootstrap_company \
     --name "ТОО Пример" --owner-login owner@example.kz --owner-name "Иван Иванов" \
     --modules forwarding --password-env OWNER_PW
   unset OWNER_PW
   ```
   Команда печатает id компании и логин (пароль - никогда), проверяет пароль валидаторами Django. Повторный
   запуск с теми же логином и названием завершится ошибкой без дублей.
7. Суперпользователь Django - только если включаете админку (`DJANGO_ADMIN_ENABLED=true`, и тогда закройте
   `/admin/` по IP в `nginx.conf`): `./deploy/dc.sh exec backend python manage.py createsuperuser`.
8. Проверка: `SMOKE_CHECK_HEADERS=1 ./deploy/smoke.sh https://app.example.kz` (код выхода 0), вход в SPA,
   `./deploy/dc.sh exec backend python manage.py check --deploy` (единственное ожидаемое предупреждение - security.W004, пока HSTS выключен).

## 5. GitHub Actions: секреты и окружения

Workflow `.github/workflows/deploy.yml`: `main` -> staging, тег `vX.Y.Z` -> production, ручной запуск
(`workflow_dispatch`: окружение + `image_tag`) для повторной выкладки и отката.

Создайте в GitHub Environments `staging` и `production`. Для **production** ОБЯЗАТЕЛЬНО включите Required reviewers
(ручное подтверждение) и Deployment branches and tags: только теги `v*` и ветка `main` (без этого любая ветка
сможет запустить выкладку в production). Workflow дополнительно проверяет тег regexp `^v[0-9]+\.[0-9]+\.[0-9]+$`;
при ручном откате принимаются только существующий `vX.Y.Z` или `sha-<7 hex>` из main (в production - только `vX.Y.Z`),
плавающий `staging` отклоняется. В каждом окружении:

| Тип | Имя | Значение |
|---|---|---|
| secret | `DEPLOY_SSH_KEY` | приватный ключ пользователя `deploy` (отдельный ключ на окружение) |
| secret | `DEPLOY_HOST` | адрес сервера |
| secret | `DEPLOY_USER` | `deploy` |
| secret | `DEPLOY_KNOWN_HOSTS` | вывод `ssh-keyscan -t ed25519 <host>` (проверка ключа хоста) |
| secret | `GHCR_PULL_TOKEN` | PAT с `read:packages` для `docker pull` на сервере |
| var | `DEPLOY_PATH` | `/opt/logistix` |
| var | `APP_URL` | `https://app.example.kz` (цель smoke-проверки) |

Образы публикуются `GITHUB_TOKEN`-ом (`packages: write`). Теги: `sha-<7 символов>` и `staging` (main);
`vX.Y.Z` и `sha-...` (релиз). `.env.prod` лежит на сервере (не в секретах GitHub). Параллельные выкладки в одно
окружение сериализуются (`concurrency`). Секреты не печатаются; токен реестра передаётся по stdin SSH.

## 6. Обновление

Штатно - через workflow (push в `main`, затем тег релиза: `git tag v1.2.0 && git push origin v1.2.0`,
подтвердить в GitHub). Вручную на сервере: `./deploy/release.sh v1.2.0` (git-ref выводится из тега; второй аргумент - явный git-ref, необязателен).
Перед рискованными миграциями - `./deploy/backup.sh`. Миграции выполняются при каждом обновлении
(`migrate`), поэтому делайте их обратно-совместимыми (сначала добавление, потом удаление).

### Финансы (этап 3A): что сделать после обновления

- Миграции `core.0009` (права `finance.override_limit`/`finance.cancel_invoice` системным ролям и
  справочник «Ставки НДС») и `finance.0001-0002` (курсы, счета, оплаты, RLS) выполняются штатно;
  после них `manage.py check_rls` должен проходить.
- Курсы валют вводятся вручную (раздел «Финансы» - «Курсы»). Без курса на дату нельзя выставить
  счёт или внести оплату в иностранной валюте (ошибка `rate_missing`). Вводите курсы к началу дня.
- Ставки НДС по умолчанию: «Без НДС», 0%, 12%, 16%; ненужные отключите в справочнике «Ставки НДС».
- Демо на Vercel + Supabase: миграции применяются временным проектом по `docs/ops/VERCEL.md`, раздел 6a.

### Документы (этап 3B)

- Выдача документов: заказ-заявка, договор, заявка перевозчику, акт, печатная форма счёта, CMR, письмо.
  Документ собирается из снимка данных на момент выдачи и версии шаблона, действовавшей тогда; правка
  заказа/клиента или нового шаблона выданный документ не меняет. Скачивание: DOCX всегда, PDF - если
  в образе есть LibreOffice (`GET /api/documents/capabilities/` возвращает `pdf_available`).
- Образ backend теперь содержит `libreoffice-writer` и шрифты (DejaVu, Liberation, Noto): он тяжелее
  примерно на 0,4 ГБ. После обновления образ нужно пересобрать (`./deploy/release.sh`), для Celery и
  gunicorn образ общий. Без пересборки PDF недоступен (503 `pdf_unavailable`), DOCX работает.
- Шаблоны компании хранятся в БД (версии, DOCX-файлы) и входят в обычный бэкап БД, отдельных файлов нет.
- Юридическая проверка: стартовые тексты шаблонов (договор, заявки, акт, CMR, письмо) - рабочие
  заготовки, не юридически выверенные формы. До боевого использования их должен просмотреть юрист
  и при необходимости заменить своими версиями шаблонов в разделе «Документы».
- Переменные окружения (необязательные): `DOCUMENT_UPLOAD_THROTTLE_RATE` (загрузка шаблонов, по умолчанию
  `30/hour` на компанию), `DOCUMENT_PDF_THROTTLE_RATE` (скачивание PDF, по умолчанию `30/min` на компанию).
  Конвертации PDF идут по одной (межпроцессная блокировка), занятость даёт 503.
- `DOCUMENTS_ALLOW_UNISOLATED_RENDER` (настройка Django, по умолчанию `False`): рендер шаблонов идёт в
  дочернем процессе с лимитами CPU/памяти; если лимиты поставить нельзя, выдаётся 503 `render_unavailable`.
  Включать рендер без изоляции можно только на изолированном стенде, в продакшене не включать.
- Не проверено: сборка образа с LibreOffice (в среде разработки нет Docker) и фактическая конвертация PDF
  на сервере. После деплоя проверьте `pdf_available` и скачайте любой документ в PDF.

## 7. Откат

1. Код/образы: `workflow_dispatch` -> окружение + предыдущий `image_tag` (он записан в
   `deploy/.previous_tag`), либо на сервере `./deploy/release.sh "$(cat deploy/.previous_tag)"` (git-ref выводится из тега: vX.Y.Z -> git-тег, sha-<hex> -> коммит).
2. Если миграция изменила схему несовместимо: остановить приложение
   (`./deploy/dc.sh stop backend worker beat`), восстановить БД из бэкапа ДО выкладки (раздел 8), затем запустить
   предыдущую версию. Откат `migrate` назад без бэкапа не предусмотрен.

## 8. Бэкапы и восстановление

`deploy/backup.sh` (запускать на хосте под `deploy`): `pg_dump -Fc` под владельцем БД (через
`docker compose exec postgres`, пароли не нужны), архив тома media, файл `.counts` (число строк по таблицам),
`.sha256`; файлы в `$BACKUP_DIR` с правами 600, метка времени UTC; шифрование GPG
(`BACKUP_GPG_RECIPIENT` - получатель или `BACKUP_GPG_PASSPHRASE_FILE` - симметрично, AES256); срок хранения
`BACKUP_KEEP_DAYS`; выгрузка `BACKUP_REMOTE` (rsync по ssh, нужен `rsync` на хосте) на **казахстанское**
хранилище; блокировка от параллельных запусков. Коды выхода: 0 успех, 1 ошибка, 2 уже выполняется,
20 копия сделана локально, но выгрузка не удалась. **Без шифрования копия содержит персональные данные в
открытом виде - в продакшене настройте шифрование.** Ключ/парольную фразу храните отдельно от бэкапов.

**Хранение на удалённом хранилище:** `backup.sh` чистит только локальный `BACKUP_DIR` (`BACKUP_KEEP_DAYS`); срок
хранения на `BACKUP_REMOTE` настраивайте отдельно (cron на стороне хранилища, lifecycle-правило).

**Расписание (cron, пользователь `deploy`, 02:30 по времени сервера):**
```cron
30 2 * * * cd /opt/logistix && ./deploy/backup.sh >>/var/log/logistix-backup.log 2>&1 || echo "backup failed" | logger -t logistix-backup
```
**systemd-таймер** (предпочтительнее: видны статус и логи):
```ini
# /etc/systemd/system/logistix-backup.service
[Service]
Type=oneshot
User=deploy
WorkingDirectory=/opt/logistix
ExecStart=/opt/logistix/deploy/backup.sh
# /etc/systemd/system/logistix-backup.timer
[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
[Install]
WantedBy=timers.target
```
`systemctl enable --now logistix-backup.timer`; мониторьте `systemctl status logistix-backup.service`
(ненулевой код = сбой, в т.ч. 20 = нет копии на удалённом хранилище).

**Восстановление** (`deploy/restore.sh [--force] [--target-db ИМЯ] [--media АРХИВ] ДАМП`): проверяет `.sha256`,
расшифровывает, отказывается трогать непустую БД без `--force`, делает `pg_restore` одной транзакцией,
заново выдаёт права `logistix_app` (`db-init.sql`, нужен `APP_DB_PASSWORD`), запускает `check_rls` под ролью
приложения, печатает число строк и сверяет с `.counts` (расхождение = код 3). ВСЕ дешёвые проверки (файлы,
контрольные суммы дампа и медиа, расшифровка, целостность архива) выполняются ДО изменения БД. Медиа и
check_rls идут через `docker compose run --rm --no-deps` и работают при остановленных сервисах; если медиа не
восстановилось уже после замены БД, скрипт выходит с кодом 4 и печатает команду для повтора. `--print-commands`
печатает docker-команды без выполнения. Боевое восстановление:
```bash
./deploy/dc.sh stop backend worker beat
./deploy/restore.sh --force --media /var/backups/logistix/logistix-<метка>-media.tar.gz.gpg \
    /var/backups/logistix/logistix-<метка>.dump.gpg
./deploy/dc.sh up -d      # тег - из deploy/.image_tag.env (текущий релиз)
```
**Ограничения `--force`:** `pg_restore --clean` заменяет объекты из дампа, но таблицы из более новых миграций,
которых в дампе нет, остаются; после восстановления на более раннюю схему запустите `./deploy/release.sh` с
соответствующим тегом (миграции дойдут до актуальной схемы). Медиа накладывается поверх (лишние файлы не удаляются).
**Учения (раз в квартал):** восстановить последнюю копию в отдельную БД и сверить: `./deploy/restore.sh
--target-db drill_$(date +%Y%m%d) <дамп>` (сверка строк с `.counts` встроена), затем `DROP DATABASE`.
Фиксируйте дату и результат.

## 9. Ротация секретов

| Что | Как |
|---|---|
| `DJANGO_SECRET_KEY` и JWT | сменить в `.env.prod`, `./deploy/dc.sh up -d backend worker beat`; **все токены станут недействительными** (повторный вход) |
| пароль роли приложения `APP_DB_PASSWORD` | `ALTER ROLE logistix_app PASSWORD '...'` в postgres (`./deploy/dc.sh exec -T postgres psql -U logistix -d logistix`), затем новое значение в `.env.prod` и `./deploy/dc.sh up -d` |
| пароль владельца `POSTGRES_PASSWORD` | `ALTER ROLE logistix PASSWORD '...'`, затем `.env.prod` |
| `REDIS_PASSWORD` | `.env.prod`, `./deploy/dc.sh up -d` (пересоздаст redis и клиентов; кэш/очередь сбросятся) |
| SSH-ключ деплоя, `GHCR_PULL_TOKEN` | заменить в GitHub Environments и на сервере (`authorized_keys`) |
| пароль GPG бэкапов | новая парольная фраза применяется к НОВЫМ копиям; старые расшифровываются старой |

После смены паролей БД выполните `./deploy/smoke.sh` и `./deploy/dc.sh logs migrate`.

## 10. Мониторинг и логи

- Логи контейнеров: `./deploy/dc.sh logs -f --tail=200 backend nginx worker`; ротация json-file 10 МБ x 5 файлов на сервис.
  Ошибки запросов (500) пишутся в stderr backend (`django.request`), доступ - в логах gunicorn и nginx.
- Состояние: `./deploy/dc.sh ps`; healthcheck есть у nginx, backend, postgres, redis, worker; у `beat` его нет (HTTP-проверка образа отключена), смотрите его логи.
- Внешний мониторинг: опрашивайте `https://app.example.kz/api/health/` (ожидается 200 и `{"status":"ok"}`)
  каждую минуту (UptimeRobot-аналог в РК либо собственный).
- Sentry: `SENTRY_DSN` пуст = выключен. Включайте только с **собственным или казахстанским** Sentry;
  отправляются исключения без тел запросов, cookie, Authorization и персональных данных
  (`send_default_pii=False`, `max_request_body_size="never"`, фильтр `before_send`).
- Диск: следите за `df -h` и `docker system df` (тома `pgdata`, `media`, логи, `BACKUP_DIR`).

## HSTS: когда и как включать

По умолчанию HSTS ВЫКЛЮЧЕН: `DJANGO_HSTS_SECONDS=0`, `DJANGO_HSTS_INCLUDE_SUBDOMAINS=false` в
`.env.prod.example`. Единственный источник — `.env.prod` (nginx HSTS не добавляет). `includeSubDomains` не
включайте: платформа обслуживает пользовательские домены и поддомены компаний, и браузер закрепит https на всех.
Порядок: убедитесь, что https работает на всех хостах, сертификат продлевается автоматически и редирект с 80
стабилен; затем `DJANGO_HSTS_SECONDS=3600` -> через неделю `604800` -> `31536000`, каждый раз
`./deploy/dc.sh up -d backend`. Заголовок Django ставит только на https-ответах (за прокси `X-Forwarded-Proto`).
Откатить закреплённый HSTS до истечения срока нельзя. При включённом HSTS `check --deploy` предупреждений
по W004 не даёт; при выключенном они ожидаемы (в CI и тесте W004 заглушается переменной `DJANGO_SILENCED_CHECKS`).

## 11. Резидентность данных (чек-лист)

- [ ] Сервер и хранилище бэкапов (`BACKUP_REMOTE`) - в Казахстане; зарубежных копий нет.
- [ ] `SENTRY_DSN` пуст или указывает на Sentry в РК.
- [ ] Распознавание документов (OCR) / внешние ИИ-сервисы НЕ подключены (этап 5+).
- [ ] Инвентарь исходящих вызовов: сейчас приложение не обращается к внешним сервисам, кроме (если включено)
  Sentry; pull образов из GHCR выполняет сервер только при выкладке; certbot обращается к Let's Encrypt
  (передаёт только домен). Почтовых/SMS-интеграций нет. Шрифты/CDN во фронтенде не используются
  (строгий CSP `default-src 'self'` это обеспечивает).
- [ ] Бэкапы зашифрованы.

## 12. Чек-лист безопасности

- [ ] `TRUST_PROXY_HEADERS=true` ТОЛЬКО за этим nginx, и nginx перезаписывает `X-Forwarded-For`
  (`proxy_set_header X-Forwarded-For $remote_addr`, файл `nginx-proxy-backend.conf`); backend не опубликован.
  Если перед nginx появится CDN/балансировщик - настройте `real_ip_header` и доверенные адреса, иначе IP
  в журнале аудита и лимиты запросов будут привязаны к балансировщику.
- [ ] `REDIS_URL` задан (compose задаёт): общие счётчики throttle между воркерами.
- [ ] Роль приложения `logistix_app` не суперпользователь и без BYPASSRLS: `migrate` вызывает `check_rls` при
  каждой выкладке; вручную: `./deploy/dc.sh exec backend python manage.py check_rls`.
- [ ] Админка выключена (`DJANGO_ADMIN_ENABLED=false`) либо `/admin/` ограничен по IP.
- [ ] `DJANGO_DEBUG=false`; `check --deploy` без предупреждений, кроме ожидаемого security.W004, пока HSTS выключен (в CI проверяется на примере окружения с заглушённым W004).
- [ ] HTTPS работает, редирект с 80; HSTS включён по разделу «HSTS» (или осознанно оставлен выключенным).
- [ ] Порты наружу: только 22/80/443 (`ss -ltnp`, `nmap` с другой машины).
- [ ] `deploy/.env.prod` права 600, в git его нет; пароли разные и случайные.
- [ ] Медиа отдаёт nginx с `X-Content-Type-Options: nosniff`, типом по расширению (картинки) и CSP `sandbox`; тело запроса
  до 3 МБ (`client_max_body_size`; файл шаблона документов до 2 МБ + накладные multipart, точный размер проверяет API); лимиты на вход (5 запросов/мин, всплеск 5) и `/api/branding/` (30/мин, всплеск 20).
- [ ] Бэкапы работают, учения проведены, копия на удалённом хранилище свежая.

## 13. Учётные записи: сброс пароля, TOTP, отзыв токенов

Почтовой отправки в системе нет (сознательно, бесплатный режим). Пароль при создании пользователя задаёт
администратор компании, а свой пароль пользователь меняет сам («Сменить пароль»). Администратор компании
пароль уже созданного пользователя изменить не может, поэтому забытый пароль (и пароль владельца платформы)
сбрасывает администратор сервера штатной командой Django.

**Предпочтительно - одноразовая ссылка (пароль администратор не видит):**
```bash
./deploy/dc.sh exec backend python manage.py issue_password_link owner@example.kz --base-url https://app.example.kz
```
Ссылка (около 2 часов, один раз) передаётся человеку личным каналом, он сам задаёт пароль на странице
`/setup-password`; прежние токены отзываются при установке нового пароля. Так же создаётся первый пароль
владельца и администраторов (`docs/ops/OWNER_ACCOUNT.md`).

**Сброс пароля штатной командой Django (администратор сервера).** Только по запросу самого владельца аккаунта, личность
подтверждается вне системы. Пароль вводится интерактивно, в аргументах и истории оболочки его нет:
```bash
./deploy/dc.sh exec backend python manage.py changepassword owner@example.kz
```
Команда `changepassword` принимает email (логин по e-mail). Для аккаунта только с телефоном:
```bash
./deploy/dc.sh exec backend python manage.py shell -c "
from getpass import getpass
from django.contrib.auth import get_user_model
from apps.core.phone import normalize_phone
u = get_user_model().objects.get(phone=normalize_phone('+7 700 000 00 00'))
u.set_password(getpass('Новый пароль: ')); u.save()
"
```
Пароль проверяется валидаторами Django только в API; при ручной установке задайте стойкий пароль сами.

**Токены.** Любая смена пароля (форма «Сменить пароль», `changepassword`, оболочка) и выход из системы
отзывают ВСЕ ранее выданные токены этого пользователя (access и refresh, на всех устройствах): `User.tokens_valid_after`.
Отзыв действует сразу, ждать срока жизни токена не нужно. Смена пароля через форму оставляет текущую сессию
на новых токенах. Смена `DJANGO_SECRET_KEY` (раздел 9) отзывает токены ВСЕХ пользователей.

**TOTP владельца платформы.** Для роли «Владелец платформы» второй фактор обязателен (для «Администратора
платформы» - если он включён). Первый вход владельца: пароль -> показ ключа -> добавление в приложение-аутентификатор
(Google Authenticator, Aegis, FreeOTP, ключ вносится вручную или по otpauth-ссылке) -> первый верный код
включает TOTP. Следующие входы: пароль + код (код принимается один раз, допуск +-30 с, 5 попыток в минуту).
Журнал платформы пишет вход, неудачный пароль/код, подключение TOTP. Секрет TOTP хранится в базе открытым
текстом, поэтому бэкапы обязательно шифруются (раздел 8) и база защищена так же, как остальные данные.

*Потерян телефон / нужен новый аутентификатор* (администратор сервера):
```bash
./deploy/dc.sh exec backend python manage.py reset_totp owner@example.kz
```
Ключ удаляется, токены отзываются, при следующем входе владелец заново подключает аутентификатор.
Владельцев платформы создаёт только команда `create_platform_owner` (раздел 4 и `docs/ops/LAUNCH.md`),
роли назначаются командой `set_platform_role`; роль `is_superuser`/`is_staff` платформенных прав не даёт.

## 14. Журнал входов: срок хранения и очистка

События входа (`login`, `login_failed`) хранятся `CompanyAuditSettings.login_audit_retention_days` дней (по умолчанию 90;
меняется в «Настройки → Компания», допустимо 30-1095). Очистка:

```bash
python manage.py purge_login_audit --dry-run   # сколько событий будет удалено
python manage.py purge_login_audit             # удалить события старше срока
```

Команда не трогает остальные записи журнала. Запускать вручную или по расписанию там, где оно есть
(на бесплатной инфраструктуре встроенного планировщика нет).

## 15. Исходящая почта компании

Каждая компания настраивает свой SMTP-сервер в «Настройки → Почта компании» (право `mail.manage_account`). Пароль ящика
хранится зашифрованным ключом `MAIL_ENCRYPTION_KEY` (если не задан - выводится из `DJANGO_SECRET_KEY`; при смене ключа
пароли ящиков придётся ввести заново, поэтому лучше задать отдельный постоянный ключ). Переменные окружения:

- `MAIL_DAILY_LIMIT` - писем в сутки на компанию (по умолчанию 200);
- `MAIL_ALLOW_PRIVATE_HOSTS=1` - разрешить SMTP-серверы во внутренней сети (только для разработки; по умолчанию запрещено
  из-за риска SSRF);
- `MAIL_SMTP_TIMEOUT` - таймаут соединения в секундах (15).

Ошибка отправки записывается в письмо коротким текстом без секретов; письмо можно отправить повторно. Нужна зависимость
`cryptography` (уже в requirements.txt).

## Известные ограничения и что не проверено

Подготовлено в среде без Docker daemon и без nginx. **Проверено:** `docker compose config -q`; `bash -n`
всех скриптов; парсинг YAML workflow; разбор `nginx.conf` парсером crossplane (контексты и аргументы директив,
но НЕ `nginx -t`); gunicorn локально (DEBUG=false, PostgreSQL, Redis) + `smoke.sh`; `migrate`/`check_rls`
под ролью приложения; `bootstrap_company`; `check --deploy` (только ожидаемое W004 при выключенном HSTS); `db-init.sql` и `initdb` с
ICU-локалью на временном кластере PostgreSQL 16; `backup.sh` -> `restore.sh` с GPG на локальном PostgreSQL со
сверкой числа строк; сборка SPA (в `index.html` нет inline-скриптов, внешних ресурсов нет).

**НЕ проверено (проверить при первом деплое):**
- сборка образов `Dockerfile.backend` и `Dockerfile.web` (никогда не собирались), `HEALTHCHECK`, права на тома
  (пользователь uid 10001 в backend, запись в `media`/`static`; чтение nginx);
- запуск nginx: `docker compose exec nginx nginx -t`, поведение `limit_req`, `resolver` Docker-DNS, заголовки,
  CSP в браузере (SPA без inline-скриптов, но проверьте консоль браузера), отдача `/media/` и `/static/`;
- реальный TLS, certbot, обновление сертификата, HSTS;
- `docker compose up` целиком: порядок запуска, `migrate` -> `backend`, healthcheck worker (`celery inspect ping`),
  `POSTGRES_INITDB_ARGS` с ICU на официальном образе (на системном PostgreSQL 16 проверено);
- GitHub Actions (`deploy.yml`) - не запускались, actionlint не использовался; окружения и секреты не созданы;
- выгрузка бэкапа через rsync на удалённое хранилище (в среде нет rsync; проверен лишь код выхода 20 при сбое);
- `release.sh` и режим `PG_MODE=docker` у `backup.sh`/`restore.sh` (проверен только `PG_MODE=local`; для docker-пути
  тест `deploy/test-scripts.sh` лишь проверяет напечатанные команды: `run`, а не `exec`);
- нагрузка, число воркеров gunicorn, лимиты памяти контейнеров.

**Известные ограничения продукта:** Sentry: `before_send` чистит события, но `before_send_transaction` и
хлебные крошки (breadcrumbs) не очищаются (включайте трассировку `SENTRY_TRACES_SAMPLE_RATE>0` осознанно); лимит входа
5 запросов в минуту на IP (+ всплеск 5) может мешать офисам за одним NAT - при жалобах поднимите `rate` в
`nginx.conf` и пересоберите web-образ; MinIO/S3 не подключены (медиа - том `media`, этап 5); пользовательские домены
компаний требуют ручного добавления в `DJANGO_ALLOWED_HOSTS`/CSRF/CORS и отдельного сертификата; один сервер
(нет отказоустойчивости); у owner-роли PostgreSQL в официальном образе права суперпользователя (используется
только `migrate` и бэкапами, приложение работает под `logistix_app`); образ nginx содержит и SPA, и конфиг,
поэтому изменение `nginx.conf` требует новой сборки web-образа; CSP админки Django не проверялась.

### Финансовая архитектура P0.1, задача 1.1: что сделать после обновления

- Миграции: `forwarding.0006` (Trip.price -> Trip.carrier_price, только состояние Django, столбец `price`
  не меняется), `forwarding.0007` (Trip.completed_at и индекс), `core.0011` (системные коды статусов рейса
  только для однозначных значений), `core.0012` (право `trips.revert_completed` роли «Администратор»).
- Отчёт ручной проверки системных кодов статусов (ничего не меняет):
  `python manage.py check_system_status_codes [--company ID]`. Для статуса, который не удалось сопоставить
  автоматически (переименован, дубликаты, иные признаки), владелец платформы назначает код вручную:
  `python manage.py assign_system_status_code --company ID --value ID --code COMPLETED [--dry-run]`.
  Пока код не назначен, правила рейса по этому коду (completed_at, защита выхода из «Завершён») не действуют.
- Заполнение времени завершения у уже завершённых рейсов по журналу аудита:
  `python manage.py backfill_trip_completed_at [--company ID] [--dry-run]`; рейсы без записи аудита
  попадают в отчёт «требует проверки», время не придумывается.
