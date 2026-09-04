#!/bin/sh
# Runs before every `web` container start (see django.Dockerfile's
# ENTRYPOINT). Idempotent on purpose — it runs on every restart, not just
# the first one, same as the old deploy's "Обновления" section always
# re-running collectstatic/migrate_schemas --shared rather than trying to
# detect whether they're needed.
#
# What it deliberately does NOT do: migrate_schemas --schema=clinicnet
# (the tenant schema) or tenant_command seed_rbac. Those touch tenant
# data and stay a manual, one-off `docker compose exec web ...` step —
# see docs/DEPLOY-DOCKER.md — same split as the manual deploy always had.
set -e

python manage.py collectstatic --noinput
python manage.py migrate_schemas --shared --noinput

exec "$@"
