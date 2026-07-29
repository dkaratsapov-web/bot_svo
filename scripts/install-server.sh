#!/usr/bin/env bash
# Полная установка бота на чистый Ubuntu-сервер одной командой.
# Идемпотентен: повторный запуск безопасен и просто доводит состояние до нужного.
#
#   curl -fsSL https://raw.githubusercontent.com/dkaratsapov-web/bot_svo/main/scripts/install-server.sh | bash
#
# Что делает:
#   1. swap 2 ГБ (нужен на серверах с 1 ГБ RAM)
#   2. Docker + compose plugin
#   3. клонирует репозиторий в /opt/bot_svo
#   4. создаёт .env (спросит BOT_TOKEN скрытым вводом, если его ещё нет)
#   5. ставит systemd-таймер автообновления инфраструктуры
#   6. поднимает стек и показывает статус
set -euo pipefail

REPO="${REPO:-https://github.com/dkaratsapov-web/bot_svo.git}"
APP_DIR="${APP_DIR:-/opt/bot_svo}"
BRANCH="${BRANCH:-main}"
SWAP_SIZE="${SWAP_SIZE:-2G}"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите от root (или через sudo)." >&2
    exit 1
fi

# --------------------------------------------------------------------------- #
log "1/6 swap"
# --------------------------------------------------------------------------- #
if swapon --show 2>/dev/null | grep -q '/swapfile'; then
    log "swap уже настроен"
else
    fallocate -l "$SWAP_SIZE" /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
sysctl -q -p /etc/sysctl.d/99-swappiness.conf || true
free -h | grep -i swap

# --------------------------------------------------------------------------- #
log "2/6 Docker"
# --------------------------------------------------------------------------- #
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker уже установлен: $(docker --version)"
else
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl git
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
        "$(dpkg --print-architecture)" \
        "$(. /etc/os-release && echo "$VERSION_CODENAME")" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
apt-get install -y -qq git >/dev/null 2>&1 || true

# --------------------------------------------------------------------------- #
log "3/6 код в $APP_DIR"
# --------------------------------------------------------------------------- #
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
    git -C "$APP_DIR" reset --hard "origin/$BRANCH" --quiet
    log "обновлено до $(git -C "$APP_DIR" rev-parse --short HEAD)"
else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --quiet --branch "$BRANCH" "$REPO" "$APP_DIR"
    log "склонировано: $(git -C "$APP_DIR" rev-parse --short HEAD)"
fi
cd "$APP_DIR"
chmod +x scripts/*.sh docker-entrypoint.sh 2>/dev/null || true
mkdir -p data backups

# --------------------------------------------------------------------------- #
log "4/6 конфигурация .env"
# --------------------------------------------------------------------------- #
if [ -f .env ] && grep -qE '^BOT_TOKEN=.+' .env; then
    log ".env уже есть, токен на месте — не трогаю"
else
    if [ ! -f .env ]; then
        cat > .env <<'ENVEOF'
IMAGE=ghcr.io/dkaratsapov-web/bot_svo:latest
MODE=polling
REDIS_URL=redis://redis:6379/0
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db
WEB_HOST=0.0.0.0
WEB_PORT=8080

# Домен нужен только для MODE=webhook
DOMAIN=
ACME_EMAIL=
WEBHOOK_URL=
WEBHOOK_SECRET=
WEBHOOK_PATH=/max/webhook

# Доступ администраторов и чаты операторов (можно заполнить позже)
ADMIN_USER_IDS=
ADMIN_CHAT_DEFAULT_ID=
ADMIN_CHAT_JOIN_ID=
ADMIN_CHAT_JOB_ID=
ADMIN_CHAT_PSY_ID=
ADMIN_CHAT_LAW_ID=
ADMIN_CHAT_OTHER_ID=

ORG_PHONE=
ORG_EMAIL=
ORG_SITE_URL=
PRIVACY_POLICY_URL=

CONSENT_VERSION=1.0
DUPLICATE_WINDOW_HOURS=24
ASK_FREE_TEXT_FOR_OTHER=false
RESPONSE_SLA_DAYS=3
LOG_LEVEL=INFO
TZ=Europe/Moscow
ENVEOF
    fi

    if [ -n "${BOT_TOKEN:-}" ]; then
        token="$BOT_TOKEN"
    elif [ -t 0 ]; then
        read -rsp 'Вставьте BOT_TOKEN (от @MasterBot) и нажмите Enter: ' token
        echo
    else
        # Скрипт запущен через pipe (curl | bash) — читаем с терминала напрямую
        read -rsp 'Вставьте BOT_TOKEN (от @MasterBot) и нажмите Enter: ' token < /dev/tty
        echo
    fi

    if [ -z "${token:-}" ]; then
        warn "Токен не введён. Впишите его вручную в $APP_DIR/.env (строка BOT_TOKEN=) и перезапустите скрипт."
    else
        # Заменяем существующую строку либо добавляем новую
        if grep -q '^BOT_TOKEN=' .env; then
            sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=${token}|" .env
        else
            echo "BOT_TOKEN=${token}" >> .env
        fi
        unset token
    fi
fi
chmod 600 .env

# --------------------------------------------------------------------------- #
log "5/6 автообновление (systemd-таймер)"
# --------------------------------------------------------------------------- #
sed "s|/opt/bot_svo|${APP_DIR}|g; s|BRANCH=main|BRANCH=${BRANCH}|" \
    deploy/bot-svo-selfupdate.service > /etc/systemd/system/bot-svo-selfupdate.service
cp deploy/bot-svo-selfupdate.timer /etc/systemd/system/bot-svo-selfupdate.timer
systemctl daemon-reload
systemctl enable --now bot-svo-selfupdate.timer >/dev/null
log "таймер включён: $(systemctl is-active bot-svo-selfupdate.timer)"

# --------------------------------------------------------------------------- #
log "6/6 запуск стека"
# --------------------------------------------------------------------------- #
mode="$(grep -E '^MODE=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
if [ "$mode" = "webhook" ]; then
    COMPOSE_ARGS="-f docker-compose.prod.yml -f docker-compose.webhook.yml"
else
    COMPOSE_ARGS="-f docker-compose.prod.yml"
fi

# shellcheck disable=SC2086
docker compose $COMPOSE_ARGS pull --quiet || warn "не удалось скачать образ — проверьте, что пакет GHCR публичный"
# shellcheck disable=SC2086
docker compose $COMPOSE_ARGS up -d --remove-orphans

sleep 5
# shellcheck disable=SC2086
docker compose $COMPOSE_ARGS ps

cat <<EOM

$(printf '\033[1;32m✓ Установка завершена\033[0m')

Режим: ${mode:-polling}
Каталог: ${APP_DIR}

Полезное:
  Логи бота:        docker compose -f docker-compose.prod.yml logs -f bot
  Статус:           docker compose -f docker-compose.prod.yml ps
  Автообновление:   systemctl status bot-svo-selfupdate.timer
  Лог обновлений:   journalctl -u bot-svo-selfupdate -n 50

Дальше всё разворачивается само: пуш в ветку ${BRANCH} -> сборка образа в
GitHub Actions -> Watchtower обновляет бота, systemd-таймер подтягивает
изменения инфраструктуры. Заходить на сервер больше не нужно.
EOM
