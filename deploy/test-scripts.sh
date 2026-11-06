#!/usr/bin/env bash
# Тесты shell-скриптов без Docker: bash deploy/test-scripts.sh
#  - dc() требует тег образа и всегда передаёт .image_tag.env вторым --env-file;
#  - restore.sh в docker-режиме использует `run`, а не `exec`, для медиа и check_rls;
#  - (если доступен PostgreSQL по PG*-переменным, по умолчанию 127.0.0.1 logistix/logistix)
#    backup -> restore с --media и GPG в одноразовую БД, сбой GPG не оставляет открытых файлов.
# Docker-путь реально НЕ выполняется (только печать команд): это ограничение теста.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAILS=0
ok() { printf 'ok    %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1" >&2; FAILS=$((FAILS + 1)); }
check() { local name="$1"; shift; if "$@"; then ok "$name"; else bad "$name"; fi; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# --- dc() без тега падает громко ---
out="$(IMAGE_TAG_FILE="$T/none.env" ENV_FILE="$HERE/.env.prod.example" "$HERE/dc.sh" ps 2>&1)"; rc=$?
check "dc.sh без .image_tag.env: код != 0" test "$rc" -ne 0
check "dc.sh без .image_tag.env: сообщение про release.sh" grep -q "release.sh" <<<"$out"

# --- dc() печатает оба env-файла ---
out="$(DC_PRINT=1 IMAGE_TAG_FILE="$HERE/.image_tag.env.example" ENV_FILE="$HERE/.env.prod.example" "$HERE/dc.sh" up -d)"
check "dc: два --env-file (.env.prod и .image_tag.env)" bash -c '[[ "$1" == *"--env-file"*".env.prod.example"*"--env-file"*".image_tag.env.example"* ]]' _ "$out"

# --- dc(): экспортированный IMAGE_TAG не перебивает .image_tag.env ---
mkdir -p "$T/stub"
printf '#!/bin/sh\necho "IMAGE_TAG=${IMAGE_TAG-unset} ARGS=$*"\n' >"$T/stub/docker"; chmod +x "$T/stub/docker"
out="$(PATH="$T/stub:$PATH" IMAGE_TAG=evil IMAGE_TAG_FILE="$HERE/.image_tag.env.example" ENV_FILE="$HERE/.env.prod.example" "$HERE/dc.sh" ps)"
check "dc: IMAGE_TAG из окружения сброшен перед compose" grep -q "^IMAGE_TAG=unset " <<<"$out"

# --- release.sh: git-ref выводится из тега (docker/git подменены заглушками) ---
printf '#!/bin/sh\necho "git $*" >>"$GIT_LOG"\n[ "$3" = rev-parse ] && echo abc1234\nexit 0\n' >"$T/stub/git"; chmod +x "$T/stub/git"
printf '#!/bin/sh\necho "IMAGE_TAG=${IMAGE_TAG-unset} $*" >>"$DOCKER_LOG"\ncase "$*" in *"$DOCKER_FAIL_ON"*) [ -n "$DOCKER_FAIL_ON" ] && exit 1;; esac\n[ "$1" = inspect ] && echo 0\nexit 0\n' >"$T/stub/docker"; chmod +x "$T/stub/docker"
# запуск release.sh с заглушками; код выхода и вывод сохраняются в $REL_RC / $T/rel.out
run_release() { # <аргументы release.sh>
  : >"$T/git.log"; : >"$T/docker.log"
  PATH="$T/stub:$PATH" GIT_LOG="$T/git.log" DOCKER_LOG="$T/docker.log" DOCKER_FAIL_ON="${DOCKER_FAIL_ON:-}" \
    IMAGE_TAG_FILE="$T/rel.env" PREVIOUS_TAG_FILE="$T/rel.prev" ENV_FILE="$HERE/.env.prod.example" \
    "$HERE/release.sh" "$@" </dev/null >"$T/rel.out" 2>&1
  REL_RC=$?
}
release_ref() { run_release "$@"; sed -n 's/^git .*checkout --detach //p' "$T/git.log"; }
check "release.sh vX.Y.Z без ref: checkout тега" test "$(release_ref v1.2.3)" = v1.2.3
check "release.sh sha-<hex> без ref: checkout коммита" test "$(release_ref sha-1a2b3c4)" = 1a2b3c4
check "release.sh явный ref сохраняется" test "$(release_ref v1.2.3 main)" = main

# (a) первый деплой: код 0, тег записан, .previous_tag не создан
rm -f "$T/rel.env" "$T/rel.env.bak" "$T/rel.prev"
run_release v1.2.3
check "release.sh первый деплой: код 0" test "$REL_RC" -eq 0
check "release.sh первый деплой: .image_tag.env с новым тегом" grep -qx "IMAGE_TAG=v1.2.3" "$T/rel.env"
check "release.sh первый деплой: .previous_tag не создан" test ! -e "$T/rel.prev"
# (b) существующий тег: новый тег, .previous_tag = прежний
printf 'IMAGE_TAG=v1.0.0\n' >"$T/rel.env"
run_release v1.2.3
check "release.sh обновление: код 0" test "$REL_RC" -eq 0
check "release.sh обновление: новый тег в файле" grep -qx "IMAGE_TAG=v1.2.3" "$T/rel.env"
check "release.sh обновление: .previous_tag = прежний" test "$(cat "$T/rel.prev" 2>/dev/null)" = v1.0.0
# (c) сбой шага выкладки: тег возвращён, код != 0
printf 'IMAGE_TAG=v1.0.0\n' >"$T/rel.env"
DOCKER_FAIL_ON="up -d" run_release v1.3.0
check "release.sh сбой up: код != 0" test "$REL_RC" -ne 0
check "release.sh сбой up: тег возвращён" grep -qx "IMAGE_TAG=v1.0.0" "$T/rel.env"
# (d) экспортированный IMAGE_TAG не доходит до compose, а файл тега при этом используется
IMAGE_TAG=staging run_release v1.4.0
check "release.sh при экспортированном IMAGE_TAG: код 0" test "$REL_RC" -eq 0
check "compose не получает экспортированный IMAGE_TAG" bash -c '! grep -q "^IMAGE_TAG=staging" "$1" && grep -q "^IMAGE_TAG=unset " "$1"' _ "$T/docker.log"
check "release.sh при экспортированном IMAGE_TAG: в файле новый тег" grep -qx "IMAGE_TAG=v1.4.0" "$T/rel.env"
rm -f "$T/rel.env" "$T/rel.env.bak" "$T/rel.prev"

# --- compose: тег закреплён, без файла тега конфиг не собирается ---
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  cfg="$(docker compose -f "$HERE/docker-compose.prod.yml" --env-file "$HERE/.env.prod.example" --env-file "$HERE/.image_tag.env.example" config 2>&1)"
  check "compose config: образ с закреплённым тегом" grep -q "logistix-backend:staging" <<<"$cfg"
  if docker compose -f "$HERE/docker-compose.prod.yml" --env-file "$HERE/.env.prod.example" config -q >/dev/null 2>&1; then
    bad "compose config без IMAGE_TAG должен падать"
  else ok "compose config без IMAGE_TAG падает"; fi
fi

# --- restore.sh --print-commands: run, не exec ---
cmds="$(PG_MODE=docker IMAGE_TAG_FILE="$HERE/.image_tag.env.example" ENV_FILE="$HERE/.env.prod.example" "$HERE/restore.sh" --print-commands 2>&1)"
media_line="$(grep -F 'tar -xzf' <<<"$cmds")"
rls_line="$(grep -F 'check_rls' <<<"$cmds")"
check "restore media: docker compose run --rm --no-deps backend" grep -Eq ' run --rm --no-deps -T backend tar ' <<<"$media_line"
check "restore media: нет exec" bash -c '[[ "$1" != *" exec "* ]]' _ "$media_line"
check "restore check_rls: run, не exec" bash -c '[[ "$1" == *" run "* && "$1" != *" exec "* ]]' _ "$rls_line"

# --- PostgreSQL-часть ---
export PGHOST="${PGHOST:-127.0.0.1}" PGPORT="${PGPORT:-5432}" PGUSER="${PGUSER:-logistix}" PGPASSWORD="${PGPASSWORD:-logistix}"
if command -v pg_isready >/dev/null && pg_isready -q -h "$PGHOST" -p "$PGPORT" && command -v gpg >/dev/null; then
  SRC=ts_src_$$; DST=ts_dst_$$
  trap 'psql -X -q -d postgres -c "DROP DATABASE IF EXISTS $SRC" -c "DROP DATABASE IF EXISTS $DST" >/dev/null 2>&1; rm -rf "$T"' EXIT
  psql -X -q -d postgres -c "CREATE DATABASE $SRC TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C.UTF-8'"
  psql -X -q -d "$SRC" -c "CREATE TABLE t(id int primary key, v text); INSERT INTO t SELECT g, 'x'||g FROM generate_series(1,25) g"
  mkdir -p "$T/media/branding/a" "$T/media-restored"; echo png >"$T/media/branding/a/l.png"
  echo "pass-phrase" >"$T/pass"; chmod 600 "$T/pass"
  printf '#!/bin/sh\necho "stub check_rls $*"\n' >"$T/py"; chmod +x "$T/py"
  common=(env PG_MODE=local POSTGRES_USER="$PGUSER" ENV_FILE=/nonexistent APP_DB_PASSWORD=logistix_app)

  "${common[@]}" POSTGRES_DB=$SRC BACKUP_DIR="$T/bk" MEDIA_DIR="$T/media" BACKUP_GPG_PASSPHRASE_FILE="$T/pass" "$HERE/backup.sh" >/dev/null 2>&1
  check "backup: код 0" test $? -eq 0
  check "backup: нет открытых .dump/.tar.gz" bash -c '! ls "$1"/*.dump "$1"/*.tar.gz >/dev/null 2>&1' _ "$T/bk"
  D="$(ls "$T"/bk/*.dump.gpg)"; M="$(ls "$T"/bk/*media*.gpg)"

  "${common[@]}" POSTGRES_DB=$DST BACKUP_GPG_PASSPHRASE_FILE="$T/pass" MEDIA_DIR="$T/media-restored" PYTHON="$T/py" \
    CHECK_RLS_DATABASE_URL=x "$HERE/restore.sh" --target-db "$DST" --media "$M" "$D" >"$T/restore.out" 2>&1
  check "restore с --media: код 0" test $? -eq 0
  check "restore: медиа восстановлено" test -f "$T/media-restored/branding/a/l.png"
  check "restore: число строк совпало" grep -q "число строк совпало" "$T/restore.out"
  check "restore: 25 строк в t" test "$(psql -X -At -d "$DST" -c 'SELECT count(*) FROM t')" = 25

  "${common[@]}" POSTGRES_DB=$DST BACKUP_GPG_PASSPHRASE_FILE="$T/pass" "$HERE/restore.sh" --target-db "$DST" "$D" >/dev/null 2>&1
  check "restore в непустую БД без --force: отказ" test $? -ne 0

  # битый архив медиа: отказ ДО изменения БД
  cp "$M" "$T/badmedia.gpg"; printf x >>"$T/badmedia.gpg"
  psql -X -q -d "$DST" -c "DELETE FROM t"
  "${common[@]}" POSTGRES_DB=$DST BACKUP_GPG_PASSPHRASE_FILE="$T/pass" MEDIA_DIR="$T/media-restored" PYTHON="$T/py" CHECK_RLS_DATABASE_URL=x \
    "$HERE/restore.sh" --force --target-db "$DST" --media "$T/badmedia.gpg" "$D" >/dev/null 2>&1
  check "restore с битым медиа: отказ" test $? -ne 0
  check "restore с битым медиа: БД не тронута (0 строк)" test "$(psql -X -At -d "$DST" -c 'SELECT count(*) FROM t')" = 0

  # сбой чистки по сроку хранения не уничтожает готовую копию
  mkdir -p "$T/failbin"; printf '#!/bin/sh\nexit 1\n' >"$T/failbin/find"; chmod +x "$T/failbin/find"
  PATH="$T/failbin:$PATH" "${common[@]}" POSTGRES_DB=$SRC BACKUP_DIR="$T/bk3" MEDIA_DIR="$T/media" \
    BACKUP_KEEP_DAYS=7 BACKUP_GPG_PASSPHRASE_FILE="$T/pass" "$HERE/backup.sh" >"$T/bk3.out" 2>&1
  check "backup: сбой чистки по сроку -> код 0" test $? -eq 0
  check "backup: сбой чистки -> предупреждение" grep -q "ПРЕДУПРЕЖДЕНИЕ: очистка" "$T/bk3.out"
  check "backup: сбой чистки -> копия на месте и сверена" bash -c 'cd "$1" && ls *.dump.gpg *.sha256 >/dev/null && sha256sum -c --quiet *.sha256' _ "$T/bk3"

  # сбой шифрования: не остаётся ни открытых, ни неполных файлов
  "${common[@]}" POSTGRES_DB=$SRC BACKUP_DIR="$T/bk2" MEDIA_DIR="$T/media" BACKUP_GPG_RECIPIENT=nobody-$$@invalid.example "$HERE/backup.sh" >/dev/null 2>&1
  check "backup: сбой GPG -> код != 0" test $? -ne 0
  check "backup: сбой GPG -> каталог без файлов копии" bash -c '[[ -z "$(find "$1" -type f ! -name .backup.lock)" ]]' _ "$T/bk2"
else
  echo "пропуск: нет PostgreSQL/gpg для проверки backup/restore"
fi

((FAILS)) && { echo "ПРОВАЛ: $FAILS" >&2; exit 1; }
echo "все проверки пройдены"
