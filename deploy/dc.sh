#!/usr/bin/env bash
# Обёртка docker compose с правильными env-файлами (.env.prod + .image_tag.env): ./deploy/dc.sh ps
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
dc "$@"
