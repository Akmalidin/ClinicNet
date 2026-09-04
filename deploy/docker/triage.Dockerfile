# AI-триаж (FastAPI, Telegram long-polling) — see docs/DEPLOY-DOCKER.md.
# Separate image from django.Dockerfile on purpose: its own, shorter
# requirements.txt, no overlap with Django's deps (same reasoning as the
# old deploy's separate triage_venv).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY triage_service/requirements.txt triage_service/requirements.txt
RUN pip install --no-cache-dir -r triage_service/requirements.txt

# triage_service is a Python package (has __init__.py) that imports itself
# as `triage_service.main:app` — copy it under /app/triage_service so that
# import path resolves the same way it does when run from the repo root.
COPY triage_service/ triage_service/

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8100
CMD ["uvicorn", "triage_service.main:app", "--host", "0.0.0.0", "--port", "8100"]
