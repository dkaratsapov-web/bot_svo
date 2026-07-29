#!/usr/bin/env bash
# Единый механизм автодеплоя: подтягивает изменения из git И новый образ,
# затем применяет compose. Заменяет Watchtower — тот требовал монтировать
# Docker-сокет в контейнер (права root на хосте) и его образ
# containrrr/watchtower не поддерживается: он говорит с Docker по API v1.25,
# который современный демон уже не принимает.
#
# Запускается systemd-таймером (см. deploy/).
# Логи: journalctl -u bot-svo-selfupdate
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bot_svo}"
BRANCH="${BRANCH:-main}"

cd "$APP_DIR"

log() { echo "[selfupdate] $*"; }

# Набор compose-файлов зависит от режима в .env (polling или webhook)
mode="$(grep -E '^MODE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
if [ "$mode" = "webhook" ]; then
    COMPOSE_ARGS=(-f docker-compose.prod.yml -f docker-compose.webhook.yml)
else
    COMPOSE_ARGS=(-f docker-compose.prod.yml)
fi

# --- 1. Изменения в репозитории (compose-файлы, скрипты, Caddyfile) --------- #
before="$(git rev-parse HEAD)"
git fetch --quiet origin "$BRANCH"
after="$(git rev-parse "origin/$BRANCH")"

if [ "$before" != "$after" ]; then
    log "git: $(git rev-parse --short HEAD) -> $(git rev-parse --short "origin/$BRANCH")"
    # .env в .gitignore и не пострадает; остальное приводим к состоянию origin.
    git reset --hard "origin/$BRANCH" --quiet
    chmod +x scripts/*.sh docker-entrypoint.sh 2>/dev/null || true
else
    log "git: изменений нет ($(git rev-parse --short HEAD))"
fi

# --- 2. Новый образ бота --------------------------------------------------- #
# Сравниваем digest до и после pull, чтобы отличить реальное обновление.
image_id() { docker image inspect --format '{{.Id}}' "$1" 2>/dev/null || echo none; }

img="$(grep -E '^IMAGE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
img="${img:-ghcr.io/dkaratsapov-web/bot_svo:latest}"

img_before="$(image_id "$img")"
docker compose "${COMPOSE_ARGS[@]}" pull --quiet || log "предупреждение: pull не удался"
img_after="$(image_id "$img")"

if [ "$img_before" != "$img_after" ]; then
    log "образ обновлён: ${img_before:0:19} -> ${img_after:0:19}"
fi

# --- 3. Применяем -------------------------------------------------------- #
# up -d пересоздаёт контейнеры только если поменялся образ или конфигурация,
# поэтому вызывать его на каждой итерации безопасно.
docker compose "${COMPOSE_ARGS[@]}" up -d --remove-orphans

# Подчищаем образы, оставшиеся после обновления (на диске 10 ГБ это важно).
docker image prune -f >/dev/null 2>&1 || true

log "готово (режим ${mode:-polling}, версия $(git rev-parse --short HEAD))"
