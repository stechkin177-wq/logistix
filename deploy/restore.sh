#!/usr/bin/env bash
# Восстановление из бэкапа deploy/backup.sh.
#   restore.sh [--force] [--target-db ИМЯ] [--media АРХИВ.tar.gz[.gpg]] ДАМП.dump[.gpg]
# По умолчанию целевая БД - $POSTGRES_DB. Непустую БД (есть таблицы в public) без --force не
# трогает. После pg_restore заново выдаёт права роли logistix_app (deploy/db-init.sql; нужен
# APP_DB_PASSWORD), запускает check_rls ролью приложения и печатает число строк по таблицам;
# если рядом лежит файл .counts от бэкапа - сверяет с ним (расхождение = код выхода 3).
#
# Коды выхода: 0 - успех; 1 - ошибка; 3 - число строк не совпало с бэкапом.
# Окружение как у backup.sh (PG_MODE=docker|local); в PG_MODE=local для check_rls нужен
# CHECK_RLS_DATABASE_URL (URL роли приложения на целевую БД), PYTHON (по умолчанию python3).
# ВАЖНО: перед восстановлением в боевую БД остановите приложение: docker compose stop backend worker beat
set -euo pipefail
umask 077
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_env "$ENV_FILE"

FORCE=0
TARGET_DB=""
MEDIA_ARCHIVE=""
DUMP=""
while (($#)); do
  case "$1" in
    --force) FORCE=1 ;;
    --target-db) TARGET_DB="${2:?--target-db требует имя}"; shift ;;
    --media) MEDIA_ARCHIVE="${2:?--media требует файл}"; shift ;;
    -h | --help) sed -n '2,13p' "$0"; exit 0 ;;
    -*) die "неизвестный параметр: $1" ;;
    *) [[ -z "$DUMP" ]] || die "укажите один файл дампа"; DUMP="$1" ;;
  esac
  shift
done
[[ -n "$DUMP" && -f "$DUMP" ]] || die "укажите существующий файл дампа (использование: restore.sh [--force] ДАМП)"
POSTGRES_USER="${POSTGRES_USER:-logistix}"
TARGET_DB="${TARGET_DB:-${POSTGRES_DB:-logistix}}"
[[ "$TARGET_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "недопустимое имя БД: $TARGET_DB"
[[ -n "${APP_DB_PASSWORD:-}" ]] || die "APP_DB_PASSWORD не задан: без него роль logistix_app получила бы пароль разработки"
export APP_DB_PASSWORD

TMPDIR_RESTORE="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_RESTORE"' EXIT

dump_dir="$(cd "$(dirname "$DUMP")" && pwd)"
dump_name="$(basename "$DUMP")"
stamp_base="${dump_dir}/${dump_name%%.dump*}"

# 1. контрольная сумма (если рядом есть .sha256 от backup.sh)
if [[ -f "$stamp_base.sha256" ]]; then
  ( cd "$dump_dir" && grep -F -- "  $dump_name" "$stamp_base.sha256" | sha256sum -c --quiet - ) \
    || die "контрольная сумма $dump_name не совпала"
  log "контрольная сумма совпала"
else
  log "ВНИМАНИЕ: файл .sha256 не найден, контрольная сумма не проверена"
fi

# 2. расшифровка
PLAIN="$DUMP"
if [[ "$dump_name" == *.gpg ]]; then
  PLAIN="$TMPDIR_RESTORE/restore.dump"
  gpg_decrypt_file "$DUMP" "$PLAIN"
fi

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
if [[ "$PG_MODE" == local ]]; then
  pg_restore --single-transaction --exit-on-error --clean --if-exists --no-owner --no-privileges \
    -d "$TARGET_DB" <"$PLAIN"
else
  dc exec -T postgres pg_restore -U "$POSTGRES_USER" --single-transaction --exit-on-error \
    --clean --if-exists --no-owner --no-privileges -d "$TARGET_DB" <"$PLAIN"
fi

# 5. права роли приложения (pg_restore --no-privileges их не переносит)
log "выдача прав logistix_app"
psql_owner -d "$TARGET_DB" -q <"$DEPLOY_DIR/db-init.sql" >/dev/null

# 6. медиа
if [[ -n "$MEDIA_ARCHIVE" ]]; then
  [[ -f "$MEDIA_ARCHIVE" ]] || die "нет файла медиа: $MEDIA_ARCHIVE"
  media_plain="$MEDIA_ARCHIVE"
  if [[ "$MEDIA_ARCHIVE" == *.gpg ]]; then
    media_plain="$TMPDIR_RESTORE/media.tar.gz"
    gpg_decrypt_file "$MEDIA_ARCHIVE" "$media_plain"
  fi
  log "восстановление медиа"
  if [[ "$PG_MODE" == local ]]; then
    [[ -n "${MEDIA_DIR:-}" ]] || die "MEDIA_DIR не задан"
    mkdir -p "$MEDIA_DIR" && tar -xzf "$media_plain" -C "$MEDIA_DIR"
  else
    dc exec -T backend tar -xzf - -C /var/lib/logistix/media <"$media_plain"
  fi
fi

# 7. RLS ролью приложения
log "check_rls ролью приложения"
if [[ "$PG_MODE" == local ]]; then
  [[ -n "${CHECK_RLS_DATABASE_URL:-}" ]] || die "CHECK_RLS_DATABASE_URL не задан (PG_MODE=local)"
  ( cd "$DEPLOY_DIR/../backend" && DATABASE_URL="$CHECK_RLS_DATABASE_URL" "${PYTHON:-python3}" manage.py check_rls )
else
  DATABASE_URL="postgres://logistix_app:${APP_DB_PASSWORD}@postgres:5432/${TARGET_DB}" \
    dc run --rm --no-deps -T -e DATABASE_URL backend python manage.py check_rls
fi

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
