#!/bin/sh
# Runs once per container start, before the CMD (gunicorn). Safe to run on
# every deploy/restart — migrate_schemas and collectstatic are idempotent.
set -e

echo "Waiting for Postgres at ${DB_HOST:-db}:${DB_PORT:-5432}..."
until python - <<'PYEOF'
import os, socket, sys
host = os.environ.get("DB_HOST", "db")
port = int(os.environ.get("DB_PORT", "5432"))
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
PYEOF
do
  sleep 1
done
echo "Postgres is up."

python manage.py collectstatic --noinput
python manage.py migrate_schemas --shared --noinput

exec "$@"
