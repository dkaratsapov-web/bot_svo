#!/usr/bin/env bash
# Самообновление инфраструктуры: подтягивает изменения из git и применяет
# compose, если что-то поменялось. Образ бота обновляет Watchtower, но
# правки в самих compose-файлах/скриптах требуют re-apply — этим и занят скрипт.
#
# Запускается systemd-таймером (см. deploy/), логи: journalctl -u bot-svo-selfupdate
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bot_svo}"
BRANCH="${BRANCH:-main}"

cd "$APP_DIR"

log() { echo "[selfupdate] $*"; }

# Определяем набор compose-файлов по режиму из .env
compose_files() {
    local mode
    mode="$(grep -E '^MODE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
    if [ "$mode" = "webhook" ]; then
        echo "-f docker-compose.prod.yml -f docker-compose.webhook.yml"
    else
        echo "-f docker-compose.prod.yml"
    fi
}

before="$(git rev-parse HEAD)"

git fetch --quiet origin "$BRANCH"
after="$(git rev-parse "origin/$BRANCH")"

if [ "$before" = "$after" ]; then
    log "изменений нет ($before)"
    exit 0
fi

log "обновление $before -> $after"

# Локальные правки не теряем: .env в .gitignore, остальное приводим к origin.
git reset --hard "origin/$BRANCH" --quiet

# shellcheck disable=SC2046
docker compose $(compose_files) pull --quiet
# shellcheck disable=SC2046
docker compose $(compose_files) up -d --remove-orphans

log "применено: $(git rev-parse --short HEAD)"
