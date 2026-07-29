#!/usr/bin/env sh
set -e

echo "[entrypoint] Применяю миграции Alembic..."
alembic upgrade head

echo "[entrypoint] Запускаю бота (MODE=${MODE:-polling})..."
exec python -m app.main
