"""Отдельный сервис (FastAPI), поверх основной БД читает только через
Django REST API — см. django_client.py и docs/PHASE5-TRIAGE-DESIGN.md
для обоснования (нет read-replica, поднимать её сейчас на общем
Postgres-кластере, который также обслуживает 3 чужих продукта,
признано отдельной, более рискованной инфраструктурной задачей).

Запуск (dev): uvicorn triage_service.main:app --reload --port 8100
Запуск (prod): свой systemd-юнит рядом с clinicnet.service, см. README.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .bot import TriageBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage_service")

_bot: TriageBot | None = None
_polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot, _polling_task
    _bot = TriageBot()
    _polling_task = asyncio.create_task(_bot.run_forever())
    logger.info("Triage service started.")
    yield
    _polling_task.cancel()
    await _bot.aclose()
    logger.info("Triage service stopped.")


app = FastAPI(title="ClinicNet AI-триаж", lifespan=lifespan)


@app.get("/health")
async def health():
    polling_alive = _polling_task is not None and not _polling_task.done()
    return {"status": "ok" if polling_alive else "degraded", "polling": polling_alive}
