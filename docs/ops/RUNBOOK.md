# Регламент эксплуатации Logistix (hoster.kz)

Стек: Docker Compose на VPS в Казахстане. Сервисы: `nginx` (прокси, SPA, статика, медиа, TLS),
`backend` (gunicorn), `migrate` (одноразовый), `worker`/`beat` (Celery), `postgres:16`, `redis:7`.
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
  docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod exec postgres \
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
docker compose -f /opt/logistix/deploy/docker-compose.prod.yml --env-file /opt/logistix/deploy/.env.prod stop nginx
H
sudo tee /etc/letsencrypt/renewal-hooks/post/logistix-start.sh >/dev/null <<'H'
#!/bin/sh
docker compose -f /opt/logistix/deploy/docker-compose.prod.yml --env-file /opt/logistix/deploy/.env.prod start nginx
H
sudo chmod +x /etc/letsencrypt/renewal-hooks/{pre,post}/logistix-*.sh
sudo certbot renew --dry-run
```
(Минута простоя раз в ~60 дней. Альтернатива без простоя: nginx уже отдаёт `/.well-known/acme-challenge/`
из тома `certbot-webroot`; после первого запуска стека можно перейти на
`certbot certonly --webroot -w <путь тома certbot-webroot> --cert-name logistix -d ...` и использовать
`--deploy-hook "docker compose ... exec nginx nginx -s reload"`. Не проверено.)

**Сертификат hoster.kz / иного удостоверяющего центра:** положите цепочку и ключ в
`/etc/letsencrypt/live/logistix/fullchain.pem` и `privkey.pem` (права ключа 600), перезагрузите nginx:
`docker compose ... exec nginx nginx -s reload`.

**HSTS** выключен по умолчанию в nginx (`deploy/nginx-security-headers.conf`, строка закомментирована) и в Django
(`DJANGO_HSTS_SECONDS`). Включайте ступенями (3600 -> 604800 -> 31536000) ТОЛЬКО после проверки, что весь
сайт и поддомены работают по https. Значения в nginx и `.env.prod` держите согласованными.

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
5. Запуск (нужные образы уже собраны CI; для первого запуска без CI - `docker compose ... build`):
   ```bash
   cd /opt/logistix
   IMAGE_TAG=staging ./deploy/release.sh staging     # pull + up -d + проверка migrate
   # либо вручную:
   docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod pull
   docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod up -d
   docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod ps -a   # migrate: Exited (0)
   ```
   `migrate` выполняет `migrate` под владельцем БД, собирает статику в общий том и запускает `check_rls`
   под ролью приложения. При ошибке `backend`/`worker`/`beat` не стартуют; смотрите
   `docker compose ... logs migrate`.
6. Первая компания и владелец (пароль - из переменной окружения или интерактивно, не в аргументах):
   ```bash
   dc="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod"
   read -rs OWNER_PW && export OWNER_PW
   $dc exec -e OWNER_PW backend python manage.py bootstrap_company \
     --name "ТОО Пример" --owner-login owner@example.kz --owner-name "Иван Иванов" \
     --modules forwarding --password-env OWNER_PW
   unset OWNER_PW
   ```
   Команда печатает id компании и логин (пароль - никогда), проверяет пароль валидаторами Django. Повторный
   запуск с теми же логином и названием завершится ошибкой без дублей.
7. Суперпользователь Django - только если включаете админку (`DJANGO_ADMIN_ENABLED=true`, и тогда закройте
   `/admin/` по IP в `nginx.conf`): `$dc exec backend python manage.py createsuperuser`.
8. Проверка: `SMOKE_CHECK_HEADERS=1 ./deploy/smoke.sh https://app.example.kz` (код выхода 0), вход в SPA,
   `$dc exec backend python manage.py check --deploy` (без предупреждений при боевых значениях).

## 5. GitHub Actions: секреты и окружения

Workflow `.github/workflows/deploy.yml`: `main` -> staging, тег `vX.Y.Z` -> production, ручной запуск
(`workflow_dispatch`: окружение + `image_tag`) для повторной выкладки и отката.

Создайте в GitHub Environments `staging` и `production`. Для **production** включите Required reviewers
(ручное подтверждение) и, по желанию, ограничение на теги. В каждом окружении:

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
подтвердить в GitHub). Вручную на сервере: `./deploy/release.sh v1.2.0 v1.2.0` (тег образа, git-ref).
Перед рискованными миграциями - `./deploy/backup.sh`. Миграции выполняются при каждом обновлении
(`migrate`), поэтому делайте их обратно-совместимыми (сначала добавление, потом удаление).

## 7. Откат

1. Код/образы: `workflow_dispatch` -> окружение + предыдущий `image_tag` (он записан в
   `deploy/.previous_tag`), либо на сервере `./deploy/release.sh $(cat deploy/.previous_tag) $(cat deploy/.previous_tag)`.
2. Если миграция изменила схему несовместимо: остановить приложение
   (`$dc stop backend worker beat`), восстановить БД из бэкапа ДО выкладки (раздел 8), затем запустить
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
приложения, печатает число строк и сверяет с `.counts` (расхождение = код 3). Боевое восстановление:
```bash
$dc stop backend worker beat
./deploy/restore.sh --force --media /var/backups/logistix/logistix-<метка>-media.tar.gz.gpg \
    /var/backups/logistix/logistix-<метка>.dump.gpg
$dc up -d
```
**Учения (раз в квартал):** восстановить последнюю копию в отдельную БД и сверить: `./deploy/restore.sh
--target-db drill_$(date +%Y%m%d) <дамп>` (сверка строк с `.counts` встроена), затем `DROP DATABASE`.
Фиксируйте дату и результат.

## 9. Ротация секретов

| Что | Как |
|---|---|
| `DJANGO_SECRET_KEY` и JWT | сменить в `.env.prod`, `up -d backend worker beat`; **все токены станут недействительными** (повторный вход) |
| пароль роли приложения `APP_DB_PASSWORD` | `ALTER ROLE logistix_app PASSWORD '...'` в postgres (`$dc exec -T postgres psql -U logistix -d logistix`), затем новое значение в `.env.prod` и `up -d` |
| пароль владельца `POSTGRES_PASSWORD` | `ALTER ROLE logistix PASSWORD '...'`, затем `.env.prod` |
| `REDIS_PASSWORD` | `.env.prod`, `up -d` (пересоздаст redis и клиентов; кэш/очередь сбросятся) |
| SSH-ключ деплоя, `GHCR_PULL_TOKEN` | заменить в GitHub Environments и на сервере (`authorized_keys`) |
| пароль GPG бэкапов | новая парольная фраза применяется к НОВЫМ копиям; старые расшифровываются старой |

После смены паролей БД выполните `./deploy/smoke.sh` и `docker compose ... logs migrate`.

## 10. Мониторинг и логи

- Логи контейнеров: `$dc logs -f --tail=200 backend nginx worker`; ротация json-file 10 МБ x 5 файлов на сервис.
  Ошибки запросов (500) пишутся в stderr backend (`django.request`), доступ - в логах gunicorn и nginx.
- Состояние: `$dc ps`; healthcheck есть у nginx, backend, postgres, redis, worker.
- Внешний мониторинг: опрашивайте `https://app.example.kz/api/health/` (ожидается 200 и `{"status":"ok"}`)
  каждую минуту (UptimeRobot-аналог в РК либо собственный).
- Sentry: `SENTRY_DSN` пуст = выключен. Включайте только с **собственным или казахстанским** Sentry;
  отправляются исключения без тел запросов, cookie, Authorization и персональных данных
  (`send_default_pii=False`, `max_request_body_size="never"`, фильтр `before_send`).
- Диск: следите за `df -h` и `docker system df` (тома `pgdata`, `media`, логи, `BACKUP_DIR`).

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
  каждой выкладке; вручную: `$dc exec backend python manage.py check_rls`.
- [ ] Админка выключена (`DJANGO_ADMIN_ENABLED=false`) либо `/admin/` ограничен по IP.
- [ ] `DJANGO_DEBUG=false`; `check --deploy` без предупреждений (в CI проверяется на примере окружения).
- [ ] HTTPS работает, редирект с 80, HSTS включён ступенями после проверки.
- [ ] Порты наружу: только 22/80/443 (`ss -ltnp`, `nmap` с другой машины).
- [ ] `deploy/.env.prod` права 600, в git его нет; пароли разные и случайные.
- [ ] Медиа отдаёт nginx с `X-Content-Type-Options: nosniff`, типом по расширению (картинки) и CSP `sandbox`; тело запроса
  до 2 МБ (`client_max_body_size`); лимиты на вход (5 запросов/мин, всплеск 5) и `/api/branding/` (30/мин, всплеск 20).
- [ ] Бэкапы работают, учения проведены, копия на удалённом хранилище свежая.

## Известные ограничения и что не проверено

Подготовлено в среде без Docker daemon и без nginx. **Проверено:** `docker compose config -q`; `bash -n`
всех скриптов; парсинг YAML workflow; разбор `nginx.conf` парсером crossplane (контексты и аргументы директив,
но НЕ `nginx -t`); gunicorn локально (DEBUG=false, PostgreSQL, Redis) + `smoke.sh`; `migrate`/`check_rls`
под ролью приложения; `bootstrap_company`; `check --deploy` без предупреждений; `db-init.sql` и `initdb` с
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
- `release.sh` и режим `PG_MODE=docker` у `backup.sh`/`restore.sh` (проверен только `PG_MODE=local`);
- нагрузка, число воркеров gunicorn, лимиты памяти контейнеров.

**Известные ограничения продукта:** MinIO/S3 не подключены (медиа - том `media`, этап 5); пользовательские домены
компаний требуют ручного добавления в `DJANGO_ALLOWED_HOSTS`/CSRF/CORS и отдельного сертификата; один сервер
(нет отказоустойчивости); у owner-роли PostgreSQL в официальном образе права суперпользователя (используется
только `migrate` и бэкапами, приложение работает под `logistix_app`); образ nginx содержит и SPA, и конфиг,
поэтому изменение `nginx.conf` требует новой сборки web-образа; CSP админки Django не проверялась.
