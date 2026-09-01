"""Env-based settings — python-decouple, same library the Django side
already uses (config/settings.py), so both halves of the project read
.env files the same way. Loaded explicitly from THIS file's own
directory (not decouple's default CWD-upward search) so the service
behaves the same whether it's started by systemd, uvicorn from the repo
root, or a test runner from anywhere — none of which are guaranteed to
have triage_service/ as the working directory.

This service's .env is its OWN file (triage_service/.env), never the
Django project's — never committed (the repo's root .gitignore already
excludes any ".env" at any depth).
"""
from pathlib import Path

from decouple import Config, RepositoryEnv

_env_path = Path(__file__).resolve().parent / ".env"
_config = Config(RepositoryEnv(str(_env_path)))

TELEGRAM_BOT_TOKEN: str = _config("TELEGRAM_BOT_TOKEN")

# Anthropic is OPTIONAL — see classifier.py. Without a key, the service
# still works end-to-end via the built-in keyword classifier; set this
# to switch on real LLM specialty-matching with no other code changes.
ANTHROPIC_API_KEY: str = _config("ANTHROPIC_API_KEY", default="")

# Full origin the Django REST API is reachable at for THIS tenant —
# includes the tenant's own host (django-tenants routes by Host header,
# not by path), e.g. "https://clinicnet.stom.asia" in prod, or
# "http://demo.localhost:8000" for local/dev testing.
DJANGO_API_BASE_URL: str = _config("DJANGO_API_BASE_URL")

# Dedicated service-account credentials (see docs/DEPLOY.md's triage-bot
# provisioning step) — holds ONLY triage.ingest, ALL branch scope. Not a
# human account, not reused for anything else.
DJANGO_SERVICE_USERNAME: str = _config("DJANGO_SERVICE_USERNAME")
DJANGO_SERVICE_PASSWORD: str = _config("DJANGO_SERVICE_PASSWORD")

# How many days ahead to search for the nearest slot before giving up.
SLOT_SEARCH_HORIZON_DAYS: int = _config("SLOT_SEARCH_HORIZON_DAYS", default=14, cast=int)
