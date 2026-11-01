#!/usr/bin/env bash
# Резервная копия: дамп БД (pg_dump -Fc, роль-владелец) + архив медиа + список количества строк.
# Файлы кладутся в $BACKUP_DIR с меткой времени (UTC), права 600, при необходимости шифруются
# GPG, считается SHA256, старые копии удаляются, копия может уходить на удалённое хранилище.
#
# Коды выхода: 0 - успех; 1 - ошибка; 2 - уже выполняется другой бэкап;
#              20 - локальная копия СДЕЛАНА, но выгрузка на BACKUP_REMOTE не удалась.
#
# Окружение (deploy/.env.prod или переменные): BACKUP_DIR, BACKUP_KEEP_DAYS, BACKUP_GPG_RECIPIENT |
# BACKUP_GPG_PASSPHRASE_FILE, BACKUP_REMOTE, BACKUP_SSH_KEY, PG_MODE=docker|local, POSTGRES_USER,
# POSTGRES_DB; в PG_MODE=local ещё PGHOST/PGPORT/PGUSER/PGPASSWORD и MEDIA_DIR (каталог медиа).
set -euo pipefail
umask 077
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_env "$ENV_FILE"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/logistix}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
POSTGRES_USER="${POSTGRES_USER:-logistix}"
POSTGRES_DB="${POSTGRES_DB:-logistix}"
[[ "$BACKUP_KEEP_DAYS" =~ ^[0-9]+$ ]] || die "BACKUP_KEEP_DAYS должно быть числом"
if [[ -z "${BACKUP_GPG_RECIPIENT:-}" && -z "${BACKUP_GPG_PASSPHRASE_FILE:-}" ]]; then
  log "ВНИМАНИЕ: шифрование выключено (ни BACKUP_GPG_RECIPIENT, ни BACKUP_GPG_PASSPHRASE_FILE)"
  ENCRYPT=0
else
  ENCRYPT=1
  if [[ -n "${BACKUP_GPG_PASSPHRASE_FILE:-}" && -z "${BACKUP_GPG_RECIPIENT:-}" ]]; then
    [[ -r "$BACKUP_GPG_PASSPHRASE_FILE" ]] || die "BACKUP_GPG_PASSPHRASE_FILE недоступен"
  fi
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || die "другой бэкап уже выполняется" 2

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="$BACKUP_DIR/logistix-$STAMP"
DUMP="$BASE.dump"
MEDIA="$BASE-media.tar.gz"
COUNTS="$BASE.counts"
SUMS="$BASE.sha256"
PARTIALS=()
cleanup() { local rc=$?; ((${#PARTIALS[@]})) && rm -f "${PARTIALS[@]}"; exit "$rc"; }
trap cleanup EXIT

log "дамп БД $POSTGRES_DB"
PARTIALS+=("$DUMP.partial")
pg_owner pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" >"$DUMP.partial"
[[ -s "$DUMP.partial" ]] || die "пустой дамп"
mv "$DUMP.partial" "$DUMP"

log "архив медиа"
PARTIALS+=("$MEDIA.partial")
if [[ "$PG_MODE" == local ]]; then
  [[ -n "${MEDIA_DIR:-}" && -d "$MEDIA_DIR" ]] || die "MEDIA_DIR не задан или не каталог"
  tar -C "$MEDIA_DIR" -czf "$MEDIA.partial" .
else
  # тар внутри контейнера backend (том media смонтирован в /var/lib/logistix/media)
  dc exec -T backend tar -C /var/lib/logistix/media -czf - . >"$MEDIA.partial"
fi
mv "$MEDIA.partial" "$MEDIA"

log "количество строк по таблицам"
row_counts "$POSTGRES_DB" >"$COUNTS"
[[ -s "$COUNTS" ]] || die "не удалось получить количество строк"

FILES=("$DUMP" "$MEDIA" "$COUNTS")
if ((ENCRYPT)); then
  ENCRYPTED=()
  for f in "$DUMP" "$MEDIA"; do
    PARTIALS+=("$f.gpg.partial")
    gpg_encrypt_file "$f" "$f.gpg.partial"
    mv "$f.gpg.partial" "$f.gpg"
    rm -f "$f"
    ENCRYPTED+=("$f.gpg")
  done
  FILES=("${ENCRYPTED[@]}" "$COUNTS")
fi

( cd "$BACKUP_DIR" && sha256sum -- "${FILES[@]##*/}" >"$SUMS" )
FILES+=("$SUMS")
chmod 600 "${FILES[@]}"
log "готово: $(printf "%s " "${FILES[@]##*/}")"

if [[ "$BACKUP_KEEP_DAYS" -gt 0 ]]; then
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'logistix-*' -mtime "+$BACKUP_KEEP_DAYS" -print -delete \
    | sed 's/^/удалено (срок хранения): /' >&2
fi

if [[ -n "${BACKUP_REMOTE:-}" ]]; then
  log "выгрузка на $BACKUP_REMOTE"
  SSH_CMD=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes)
  [[ -n "${BACKUP_SSH_KEY:-}" ]] && SSH_CMD+=(-i "$BACKUP_SSH_KEY")
  if ! rsync -e "${SSH_CMD[*]}" --chmod=F600 -- "${FILES[@]}" "$BACKUP_REMOTE"; then
    log "ОШИБКА: выгрузка на удалённое хранилище не удалась (локальная копия сохранена)"
    exit 20
  fi
  log "выгрузка завершена"
fi
