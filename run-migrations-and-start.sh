#!/bin/sh
set -e

echo "[migrate] Running Alembic migrations..."
cd /app/api
.venv/bin/alembic upgrade head
echo "[migrate] Database schema is up to date."

cd /app
exec sh /app/start.sh
