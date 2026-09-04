# Django/gunicorn image — see docs/DEPLOY-DOCKER.md.
#
# Build context is the repo root (docker-compose.yml passes `context: .`)
# so this can COPY the whole project; keep it slim with .dockerignore.
FROM python:3.12-slim

# psycopg2-binary needs libpq at runtime; build-essential+libpq-dev only
# for the (rare) case a future dependency needs to compile — removed in
# the same layer to keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==26.2.0

COPY apps/ apps/
COPY config/ config/
COPY manage.py .
COPY deploy/docker/django-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Runs as a non-root user, same principle as www-data on the old
# systemd-based deploy — no reason a compromised gunicorn worker needs
# root inside its own container.
#
# /app/staticfiles is chown'ed HERE, before USER switches away from root
# and before docker-compose.yml ever mounts static_volume over it: Docker
# initializes a brand-new named volume by copying whatever already exists
# at its mount point in the image (content + ownership) — skip this and
# the volume comes up root-owned, and collectstatic (running as `app`)
# fails with PermissionError on every container start.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/staticfiles \
    && chown -R app:app /app
USER app

EXPOSE 8041
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8041", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
