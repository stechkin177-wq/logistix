#!/usr/bin/env bash
# Дымовая проверка развёрнутого стека.   smoke.sh [BASE_URL]   (по умолчанию https://localhost)
# Переменные: SMOKE_SKIP_WEB=1 - не проверять SPA на "/"; SMOKE_CHECK_HEADERS=1 - проверять
# заголовки безопасности; SMOKE_INSECURE=1 - не проверять TLS-сертификат (только тесты);
# SMOKE_TIMEOUT (сек, по умолчанию 10); SMOKE_HOST_HEADER - подменить Host (для проверки до DNS).
# Код выхода != 0 при любом сбое (в том числе если адрес недоступен).
set -uo pipefail

BASE_URL="${1:-${SMOKE_BASE_URL:-https://localhost}}"
BASE_URL="${BASE_URL%/}"
TIMEOUT="${SMOKE_TIMEOUT:-10}"
CURL=(curl -sS --max-time "$TIMEOUT" -o /dev/stdout)
[[ "${SMOKE_INSECURE:-0}" == 1 ]] && CURL+=(-k)
[[ -n "${SMOKE_HOST_HEADER:-}" ]] && CURL+=(-H "Host: $SMOKE_HOST_HEADER")

FAILS=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1" >&2; FAILS=$((FAILS + 1)); }

# req METHOD PATH [curl-аргументы...] -> BODY, STATUS, HEADERS (заголовки в нижнем регистре)
req() {
  local method="$1" path="$2"
  shift 2
  local hdr
  hdr="$(mktemp)"
  BODY="$("${CURL[@]}" -X "$method" -D "$hdr" -w $'\n%{http_code}' "$@" "$BASE_URL$path" 2>/dev/null)"
  local rc=$?
  if ((rc != 0)) || [[ -z "$BODY" ]]; then
    STATUS=000
    BODY=""
    HEADERS=""
  else
    STATUS="${BODY##*$'\n'}"
    BODY="${BODY%$'\n'*}"
    HEADERS="$(tr -d '\r' <"$hdr" | tr 'A-Z' 'a-z')"
  fi
  rm -f "$hdr"
}

# 1. health
req GET /api/health/
if [[ "$STATUS" == 200 && "$BODY" == *'"status"'*'"ok"'* ]]; then pass "GET /api/health/ -> 200 {status: ok}"
else fail "GET /api/health/ -> $STATUS ${BODY:0:120}"; fi

# 2. публичное оформление экрана входа: JSON с настройками по умолчанию
req GET "/api/branding/?host=smoke-check.invalid"
if [[ "$STATUS" == 200 && "$BODY" == *'{'* && "$BODY" == *'primary_color'* ]]; then
  pass "GET /api/branding/?host=x -> 200 JSON с оформлением по умолчанию"
else fail "GET /api/branding/?host=x -> $STATUS ${BODY:0:120}"; fi

# 3. неверный вход: 401 с общим сообщением, не 500
req POST /api/auth/login/ -H 'Content-Type: application/json' \
  --data '{"login":"smoke-no-such-user@invalid.example","password":"wrong-password-0"}'
if [[ "$STATUS" == 401 && "$BODY" != *Traceback* && "$BODY" != *'"detail"'*'не найден'* ]]; then
  pass "POST /api/auth/login/ (неверные данные) -> 401"
else fail "POST /api/auth/login/ (неверные данные) -> $STATUS ${BODY:0:160}"; fi

# 4. заголовки безопасности
if [[ "${SMOKE_CHECK_HEADERS:-0}" == 1 ]]; then
  req GET /api/health/
  if [[ "$HEADERS" == *'x-content-type-options: nosniff'* ]]; then pass "X-Content-Type-Options: nosniff"
  else fail "нет X-Content-Type-Options: nosniff"; fi
  if [[ "$HEADERS" == *'x-frame-options: deny'* ]]; then pass "X-Frame-Options: DENY"
  else fail "нет X-Frame-Options: DENY"; fi
fi

# 5. SPA
if [[ "${SMOKE_SKIP_WEB:-0}" != 1 ]]; then
  req GET /
  if [[ "$STATUS" == 200 && "$BODY" == *'id="root"'* ]]; then pass "GET / -> HTML SPA (#root)"
  else fail "GET / -> $STATUS (нет #root)"; fi
fi

if ((FAILS)); then
  printf 'ИТОГ: %d проверок не пройдено (%s)\n' "$FAILS" "$BASE_URL" >&2
  exit 1
fi
echo "ИТОГ: все проверки пройдены ($BASE_URL)"
