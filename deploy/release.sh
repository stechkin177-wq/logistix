#!/usr/bin/env bash
# Выкладка на сервере (вызывается из .github/workflows/deploy.yml по SSH или вручную):
#   deploy/release.sh <IMAGE_TAG> [GIT_REF]
# GIT_REF необязателен: для vX.Y.Z берётся одноимённый git-тег, для sha-<hex> - коммит <hex>
# (откат: ./deploy/release.sh "$(cat deploy/.previous_tag)").
# Токен чтения GHCR (read:packages) - в stdin, если сервер ещё не залогинен: он не попадает ни
# в argv, ни в логи. Файл deploy/.env.prod должен лежать на сервере заранее (в git его нет).
# Шаги: git checkout GIT_REF (если задан) -> docker compose pull -> up -d (ждёт успешный migrate)
# -> проверка кода выхода migrate. Код выхода != 0 при любой неудаче; прошлый тег - в
# deploy/.previous_tag, текущий - deploy/.image_tag.env (для отката: release.sh $(cat deploy/.previous_tag)).
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

IMAGE_TAG="${1:?использование: release.sh <IMAGE_TAG> [GIT_REF]}"
GIT_REF="${2:-}"
[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || die "недопустимый тег образа"
if [[ -z "$GIT_REF" ]]; then
  if [[ "$IMAGE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then GIT_REF="$IMAGE_TAG"
  elif [[ "$IMAGE_TAG" =~ ^sha-([0-9a-f]{7,40})$ ]]; then GIT_REF="${BASH_REMATCH[1]}"
  fi
fi
[[ -z "$GIT_REF" || "$GIT_REF" =~ ^[A-Za-z0-9._/-]{1,128}$ ]] || die "недопустимый git ref"
[[ -f "$ENV_FILE" ]] || die "нет $ENV_FILE (создайте из deploy/.env.prod.example)"

if [[ ! -t 0 ]]; then
  IFS= read -r GHCR_TOKEN || true
  if [[ -n "${GHCR_TOKEN:-}" ]]; then
    printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:-token}" --password-stdin >/dev/null
    log "вход в ghcr.io выполнен"
  fi
fi

if [[ -n "$GIT_REF" ]]; then
  git -C "$DEPLOY_DIR/.." fetch --tags --prune origin
  git -C "$DEPLOY_DIR/.." checkout --detach "$GIT_REF"
  log "исходники: $(git -C "$DEPLOY_DIR/.." rev-parse --short HEAD)"
fi

# Единый источник тега: .image_tag.env читают ВСЕ вызовы compose (lib.sh dc). Если выкладка
# не удастся, возвращаем прежний тег.
current=""
if [[ -f "$IMAGE_TAG_FILE" ]]; then
  current="$(sed -n 's/^IMAGE_TAG=//p' "$IMAGE_TAG_FILE")"
  cp -p "$IMAGE_TAG_FILE" "$IMAGE_TAG_FILE.bak"
fi
revert_tag() {
  if [[ -f "$IMAGE_TAG_FILE.bak" ]]; then mv -f "$IMAGE_TAG_FILE.bak" "$IMAGE_TAG_FILE"; else rm -f "$IMAGE_TAG_FILE"; fi
}
trap 'rc=$?; ((rc)) && revert_tag; exit $rc' EXIT
( umask 077; printf 'IMAGE_TAG=%s\n' "$IMAGE_TAG" >"$IMAGE_TAG_FILE" )
chmod 600 "$IMAGE_TAG_FILE"
log "pull образов, тег $IMAGE_TAG"
dc pull
log "up -d (ждёт миграции и healthcheck backend)"
if ! dc up -d --remove-orphans; then
  log "ОШИБКА: up -d не удался; журнал migrate:"
  dc logs --no-color --tail=100 migrate >&2 || true
  exit 1
fi

migrate_id="$(dc ps -a -q migrate)"
exit_code="$(docker inspect -f '{{.State.ExitCode}}' "$migrate_id")"
if [[ "$exit_code" != 0 ]]; then
  dc logs --no-color --tail=100 migrate >&2 || true
  die "migrate завершился с кодом $exit_code"
fi

if [[ -n "$current" && "$current" != "$IMAGE_TAG" ]]; then printf '%s\n' "$current" >"$DEPLOY_DIR/.previous_tag"; fi
rm -f "$IMAGE_TAG_FILE.bak"
dc ps
log "выкладка $IMAGE_TAG завершена"
