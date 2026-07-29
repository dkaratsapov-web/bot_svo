#!/usr/bin/env sh
# Ежедневный бэкап SQLite с ротацией (по умолчанию 30 дней).
set -e

DB_PATH="${DB_PATH:-./data/bot.db}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
  echo "[backup] БД не найдена: $DB_PATH — пропускаю"
  exit 0
fi

STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/bot_${STAMP}.db"

# Консистентный бэкап через .backup, если доступен sqlite3; иначе — копия.
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB_PATH" ".backup '$DEST'"
else
  cp "$DB_PATH" "$DEST"
fi
echo "[backup] Создан $DEST"

# Ротация: удаляем бэкапы старше RETENTION_DAYS.
find "$BACKUP_DIR" -name 'bot_*.db' -type f -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true
echo "[backup] Ротация: удалены бэкапы старше ${RETENTION_DAYS} дней"
