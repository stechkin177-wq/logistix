#!/usr/bin/env bash
# Восстановление из бэкапа deploy/backup.sh.
#   restore.sh [--force] [--target-db ИМЯ] [--media АРХИВ.tar.gz[.gpg]] [--print-commands] ДАМП.dump[.gpg]
# По умолчанию целевая БД - $POSTGRES_DB. Непустую БД (есть таблицы в public) без --force не
# трогает; --force использует pg_restore --clean: объекты из дампа заменяются, а таблицы из
# более новых миграций, которых в дампе нет, ОСТАЮТСЯ; медиа накладывается поверх, а не заменяет.
# Порядок: ВСЕ дешёвые проверки (файлы, контрольные суммы, расшифровка) - ДО изменения БД;
# затем pg_restore, права logistix_app (deploy/db-init.sql, нужен APP_DB_PASSWORD), медиа,
# check_rls ролью приложения, число строк (сверка с .counts рядом с дампом).
# --print-commands: напечатать docker-команды шагов pg_restore/медиа/check_rls и выйти.
#
# Коды выхода: 0 - успех; 1 - ошибка; 3 - число строк не совпало с бэкапом;
#              4 - БД восстановлена, но не восстановлено медиа (см. сообщение).
# Окружение как у backup.sh (PG_MODE=docker|local); в PG_MODE=local для check_rls нужен
# CHECK_RLS_DATABASE_URL (URL роли приложения на целевую БД), PYTHON (по умолчанию python3).
# Шаги docker-режима идут через `docker compose run --rm --no-deps` (работают при остановленных
# backend/worker/beat), а не через `exec`. Остановите приложение перед боевым восстановлением.
set -euo pipefail
umask 077
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_env "$ENV_FILE"

FORCE=0
PRINT=0
TARGET_DB=""
MEDIA_ARCHIVE=""
DUMP=""
while (($#)); do
  case "$1" in
    --force) FORCE=1 ;;
    --print-commands) PRINT=1 ;;
    --target-db) TARGET_DB="${2:?--target-db требует имя}"; shift ;;
    --media) MEDIA_ARCHIVE="${2:?--media требует файл}"; shift ;;
    -h | --help) sed -n '2,19p' "$0"; exit 0 ;;
    -*) die "неизвестный параметр: $1" ;;
    *) [[ -z "$DUMP" ]] || die "укажите один файл дампа"; DUMP="$1" ;;
  esac
  shift
done
POSTGRES_USER="${POSTGRES_USER:-logistix}"
TARGET_DB="${TARGET_DB:-${POSTGRES_DB:-logistix}}"
[[ "$TARGET_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "недопустимое имя БД: $TARGET_DB"

# --- шаги, содержащие команды (используются и для печати, и для выполнения) ---
step_pg_restore() { # stdin - дамп
  if [[ "$PG_MODE" == local ]]; then
    pg_restore --single-transaction --exit-on-error --clean --if-exists --no-owner --no-privileges \
      -d "$TARGET_DB"
  else
    dc exec -T postgres pg_restore -U "$POSTGRES_USER" --single-transaction --exit-on-error \
      --clean --if-exists --no-owner --no-privileges -d "$TARGET_DB"
  fi
}
step_media() { # stdin - tar.gz
  if [[ "$PG_MODE" == local ]]; then
    [[ -n "${MEDIA_DIR:-}" ]] || die "MEDIA_DIR не задан"
    mkdir -p "$MEDIA_DIR" && tar -xzf - -C "$MEDIA_DIR"
  else
    # run, не exec: работает при остановленном backend. Запись идёт под пользователем образа
    # (uid 10001, владелец тома media из Dockerfile.backend), поэтому права файлов верные.
    dc run --rm --no-deps -T backend tar -xzf - -C /var/lib/logistix/media
  fi
}
step_check_rls() {
  if [[ "$PG_MODE" == local ]]; then
    [[ -n "${CHECK_RLS_DATABASE_URL:-}" ]] || die "CHECK_RLS_DATABASE_URL не задан (PG_MODE=local)"
    ( cd "$DEPLOY_DIR/../backend" && DATABASE_URL="$CHECK_RLS_DATABASE_URL" "${PYTHON:-python3}" manage.py check_rls )
  else
    DATABASE_URL="postgres://logistix_app:${APP_DB_PASSWORD}@postgres:5432/${TARGET_DB}" \
      dc run --rm --no-deps -T -e DATABASE_URL backend python manage.py check_rls
  fi
}

if ((PRINT)); then
  DC_PRINT=1
  APP_DB_PASSWORD="${APP_DB_PASSWORD:-PASSWORD}"
  step_pg_restore </dev/null
  step_media </dev/null
  step_check_rls
  exit 0
fi

[[ -n "$DUMP" && -f "$DUMP" ]] || die "укажите существующий файл дампа (использование: restore.sh [--force] ДАМП)"
[[ -n "${APP_DB_PASSWORD:-}" ]] || die "APP_DB_PASSWORD не задан: без него роль logistix_app получила бы пароль разработки"
export APP_DB_PASSWORD
if [[ -n "$MEDIA_ARCHIVE" && ! -r "$MEDIA_ARCHIVE" ]]; then die "нет файла медиа: $MEDIA_ARCHIVE"; fi

TMPDIR_RESTORE="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_RESTORE"' EXIT

# 1. контрольные суммы (если рядом есть .sha256 от backup.sh) - для дампа и для медиа
verify_sum() { # verify_sum <файл>
  local file="$1" dir name base
  dir="$(cd "$(dirname "$file")" && pwd)"; name="$(basename "$file")"
  base="${dir}/${name%%.dump*}"; [[ "$name" == *media* ]] && base="${dir}/${name%%-media*}"
  if [[ -f "$base.sha256" ]]; then
    ( cd "$dir" && grep -F -- "  $name" "$base.sha256" | sha256sum -c --quiet - ) \
      || die "контрольная сумма $name не совпала"
    log "контрольная сумма $name совпала"
  else
    log "ВНИМАНИЕ: файл .sha256 для $name не найден, контрольная сумма не проверена"
  fi
}
verify_sum "$DUMP"
[[ -z "$MEDIA_ARCHIVE" ]] || verify_sum "$MEDIA_ARCHIVE"

dump_dir="$(cd "$(dirname "$DUMP")" && pwd)"
dump_name="$(basename "$DUMP")"
stamp_base="${dump_dir}/${dump_name%%.dump*}"

# 2. расшифровка - тоже до изменения БД
PLAIN="$DUMP"
if [[ "$dump_name" == *.gpg ]]; then
  PLAIN="$TMPDIR_RESTORE/restore.dump"
  gpg_decrypt_file "$DUMP" "$PLAIN" || die "не удалось расшифровать дамп"
fi
media_plain="$MEDIA_ARCHIVE"
if [[ -n "$MEDIA_ARCHIVE" && "$MEDIA_ARCHIVE" == *.gpg ]]; then
  media_plain="$TMPDIR_RESTORE/media.tar.gz"
  gpg_decrypt_file "$MEDIA_ARCHIVE" "$media_plain" || die "не удалось расшифровать архив медиа"
fi
[[ -z "$media_plain" ]] || tar -tzf "$media_plain" >/dev/null || die "архив медиа повреждён"

# 3. целевая БД: создать, если нет; непустую без --force не трогать
exists="$(psql_owner -d postgres -At -c "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB'")"
if [[ -z "$exists" ]]; then
  log "создаю БД $TARGET_DB (UTF-8; ${RESTORE_CREATE_DB_OPTS:-LOCALE 'C.UTF-8'})"
  psql_owner -d postgres -c "CREATE DATABASE \"$TARGET_DB\" TEMPLATE template0 ENCODING 'UTF8' ${RESTORE_CREATE_DB_OPTS:-LOCALE 'C.UTF-8'}"
fi
tables="$(psql_owner -d "$TARGET_DB" -At -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
if [[ "$tables" -gt 0 && "$FORCE" -ne 1 ]]; then
  die "в БД $TARGET_DB уже есть таблицы ($tables); перезапись только с --force"
fi

# 4. восстановление одной транзакцией
log "pg_restore в $TARGET_DB"
step_pg_restore <"$PLAIN"

# 5. права роли приложения (pg_restore --no-privileges их не переносит)
log "выдача прав logistix_app"
psql_owner -d "$TARGET_DB" -q <"$DEPLOY_DIR/db-init.sql" >/dev/null

# 6. медиа (БД уже заменена: при сбое - понятная инструкция и код 4)
if [[ -n "$media_plain" ]]; then
  log "восстановление медиа"
  if ! step_media <"$media_plain"; then
    log "ОШИБКА: БД $TARGET_DB ВОССТАНОВЛЕНА, но медиа НЕ восстановлено; check_rls и сверка строк не выполнялись."
    if [[ "$PG_MODE" == local ]]; then
      log "Повторите только медиа: tar -xzf <архив> -C \"\$MEDIA_DIR\", затем check_rls ролью приложения на БД $TARGET_DB (CHECK_RLS_DATABASE_URL)"
    else
      log "Повторите только медиа: ./deploy/dc.sh run --rm --no-deps -T backend tar -xzf - -C /var/lib/logistix/media < <архив.tar.gz>"
      log "затем: ./deploy/dc.sh run --rm --no-deps -e DATABASE_URL=postgres://logistix_app:<APP_DB_PASSWORD>@postgres:5432/$TARGET_DB backend python manage.py check_rls"
    fi
    exit 4
  fi
fi

# 7. RLS ролью приложения
log "check_rls ролью приложения"
step_check_rls

# 8. число строк
row_counts "$TARGET_DB" >"$TMPDIR_RESTORE/counts"
echo "--- число строк по таблицам ($TARGET_DB) ---"
cat "$TMPDIR_RESTORE/counts"
if [[ -f "$stamp_base.counts" ]]; then
  if diff -u "$stamp_base.counts" "$TMPDIR_RESTORE/counts" >&2; then
    log "число строк совпало с бэкапом ($(wc -l <"$TMPDIR_RESTORE/counts") таблиц)"
  else
    die "число строк НЕ совпало с бэкапом" 3
  fi
else
  log "файл .counts рядом с дампом не найден: сверка пропущена"
fi
log "восстановление завершено"
