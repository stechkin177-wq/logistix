# Общие функции deploy/*.sh (подключается через source). Секреты не попадают в argv и логи.
# shellcheck shell=bash

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$DEPLOY_DIR/.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-$DEPLOY_DIR/docker-compose.prod.yml}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "ОШИБКА: $*"; exit "${2:-1}"; }

# Читает KEY=VALUE построчно (без выполнения кода) в окружение скрипта. Уже заданные в
# окружении переменные имеют приоритет над файлом.
load_env() {
  local file="$1" line key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# || -z "${line//[[:space:]]/}" ]] && continue
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -z "${!key+x}" ]]; then
      export "$key=$value"
    fi
  done <"$file"
}

# Режим доступа к PostgreSQL:
#   docker (по умолчанию) - команды выполняются в контейнере postgres через docker compose;
#                           пароль не нужен (локальный сокет), на argv/в окружении хоста нет секретов;
#   local                 - pg_dump/psql с хоста, параметры из PGHOST/PGPORT/PGUSER/PGPASSWORD (env).
PG_MODE="${PG_MODE:-docker}"

# Тег образа - ЕДИНЫЙ источник: deploy/.image_tag.env (пишет только release.sh). Каждый вызов
# compose читает его вторым --env-file; без файла dc() падает (иначе подставился бы чужой тег).
IMAGE_TAG_FILE="${IMAGE_TAG_FILE:-$DEPLOY_DIR/.image_tag.env}"

# DC_PRINT=1 - только напечатать команду (для проверки состава команд без Docker)
dc() {
  # экспортированный IMAGE_TAG приоритетнее --env-file и подменил бы тег из .image_tag.env
  unset IMAGE_TAG
  if [[ ! -f "$IMAGE_TAG_FILE" ]]; then
    die "нет $IMAGE_TAG_FILE: тег образа задаёт deploy/release.sh <тег> (первый деплой - release.sh)"
  fi
  if [[ "${DC_PRINT:-0}" == 1 ]]; then
    printf 'docker compose -f %s --env-file %s --env-file %s' "$COMPOSE_FILE" "$ENV_FILE" "$IMAGE_TAG_FILE"
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" --env-file "$IMAGE_TAG_FILE" "$@"
}

# pg_owner <команда pg_*> [аргументы...] - выполнить клиентскую утилиту ролью-ВЛАДЕЛЬЦЕМ
pg_owner() {
  if [[ "$PG_MODE" == local ]]; then
    "$@"
  else
    dc exec -T postgres "$@"
  fi
}

# psql_owner <аргументы psql> - SQL ролью-владельцем; stdin пробрасывается
psql_owner() {
  if [[ "$PG_MODE" == local ]]; then
    psql -X -v ON_ERROR_STOP=1 "$@"
  else
    dc exec -T -e APP_DB_PASSWORD postgres psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$@"
  fi
}

# Количество строк во всех таблицах схемы public (под ролью-владельцем: суперпользователь
# обходит RLS, поэтому видны все компании). Вывод: "таблица<TAB>число", отсортирован.
row_counts() {
  local db="$1"
  psql_owner -d "$db" -At -F $'\t' -c "
    SELECT table_name,
           (xpath('/row/c/text()',
                  query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name),
                               false, true, '')))[1]::text
      FROM information_schema.tables
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
     ORDER BY table_name"
}

gpg_encrypt_file() { # gpg_encrypt_file <in> <out>
  local in="$1" out="$2"
  if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
    gpg --batch --yes --trust-model always --recipient "$BACKUP_GPG_RECIPIENT" \
      --output "$out" --encrypt "$in"
  else
    gpg --batch --yes --pinentry-mode loopback --passphrase-file "$BACKUP_GPG_PASSPHRASE_FILE" \
      --symmetric --cipher-algo AES256 --output "$out" "$in"
  fi
}

gpg_decrypt_file() { # gpg_decrypt_file <in> <out>
  local in="$1" out="$2"
  if [[ -n "${BACKUP_GPG_PASSPHRASE_FILE:-}" ]]; then
    gpg --batch --yes --pinentry-mode loopback --passphrase-file "$BACKUP_GPG_PASSPHRASE_FILE" \
      --output "$out" --decrypt "$in"
  else
    gpg --batch --yes --output "$out" --decrypt "$in"
  fi
}
