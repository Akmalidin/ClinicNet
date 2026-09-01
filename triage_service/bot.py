"""Per-chat conversation state machine. In-memory only — restarting the
service loses in-progress conversations (a patient mid-triage would need
to start over). Documented, deliberate scope limit for this first cut;
persisting state (Redis, or a DB table) is a follow-up, not required for
the bot to be useful. A finished conversation's OUTCOME is durable
though — it's already been POSTed to Django as a TriageSuggestion by the
time this dict forgets about it.
"""
from __future__ import annotations

import logging

from . import config
from .classifier import get_classifier
from .django_client import DjangoClient
from .telegram_client import TelegramClient

logger = logging.getLogger("triage_service.bot")


class Stage:
    AWAITING_SYMPTOM = "awaiting_symptom"
    AWAITING_PHONE = "awaiting_phone"


class TriageBot:
    def __init__(self):
        self.telegram = TelegramClient()
        self.django = DjangoClient()
        self.classifier = get_classifier(config.ANTHROPIC_API_KEY)
        self._sessions: dict[int, dict] = {}
        self._specialties_cache: list[dict] | None = None

    async def aclose(self):
        await self.telegram.aclose()
        await self.django.aclose()

    async def _specialties(self) -> list[dict]:
        if self._specialties_cache is None:
            self._specialties_cache = await self.django.list_specialties()
        return self._specialties_cache

    async def run_forever(self):
        logger.info("Triage bot polling started.")
        while True:
            updates = await self.telegram.get_updates()
            for update in updates:
                try:
                    await self._handle_update(update)
                except Exception:
                    logger.exception("Failed to handle update %s", update.get("update_id"))

    async def _handle_update(self, update: dict):
        message = update.get("message")
        if not message:
            return
        chat_id = message["chat"]["id"]
        session = self._sessions.setdefault(chat_id, {"stage": Stage.AWAITING_SYMPTOM})

        if session["stage"] == Stage.AWAITING_SYMPTOM:
            await self._handle_symptom(chat_id, session, message)
        elif session["stage"] == Stage.AWAITING_PHONE:
            await self._handle_phone(chat_id, session, message)

    async def _handle_symptom(self, chat_id: int, session: dict, message: dict):
        text = message.get("text", "").strip()
        if not text:
            await self.telegram.send_message(chat_id, "Опишите, пожалуйста, вашу жалобу текстом.")
            return

        specialties = await self._specialties()
        specialty_code = self.classifier.classify(text, specialties)
        if not specialty_code:
            names = ", ".join(s["name"] for s in specialties) or "уточните у администратора"
            await self.telegram.send_message(
                chat_id,
                "Не смог однозначно понять, к какому специалисту вас направить. "
                f"Опишите подробнее (доступные направления: {names}).",
            )
            return

        slot = await self.django.find_nearest_slot(specialty_code, config.SLOT_SEARCH_HORIZON_DAYS)
        if not slot:
            await self.telegram.send_message(
                chat_id,
                "К сожалению, свободных окон в ближайшее время не нашли — "
                "администратор свяжется с вами, чтобы подобрать время вручную.",
            )
            self._sessions.pop(chat_id, None)
            return

        matched = next(s for s in specialties if s["code"] == specialty_code)
        session.update(
            stage=Stage.AWAITING_PHONE,
            symptom_text=text,
            specialty_id=matched["id"],
            specialty_name=matched["name"],
            slot=slot,
        )
        await self.telegram.send_message(
            chat_id,
            f"Похоже, вам нужен специалист: {matched['name']}.\n"
            f"Ближайшее окно: {slot['starts_at']} в филиале «{slot['branch_name']}».\n"
            "Поделитесь номером телефона, чтобы координатор мог подтвердить запись.",
            request_contact=True,
        )

    async def _handle_phone(self, chat_id: int, session: dict, message: dict):
        contact = message.get("contact")
        phone = contact["phone_number"] if contact else message.get("text", "").strip()
        if not phone:
            await self.telegram.send_message(
                chat_id, "Нужен номер телефона — поделитесь контактом или напишите его текстом.",
                request_contact=True,
            )
            return

        from_user = message.get("from", {})
        contact_name = " ".join(
            filter(None, [from_user.get("first_name"), from_user.get("last_name")])
        ) or "Пациент Telegram"

        slot = session["slot"]
        await self.django.ingest_suggestion({
            "channel": "telegram",
            "external_chat_id": str(chat_id),
            "contact_name": contact_name,
            "contact_phone": phone,
            "symptom_text": session["symptom_text"],
            "matched_specialty": session["specialty_id"],
            "branch": slot["branch"],
            "suggested_doctor": slot["doctor"],
            "suggested_starts_at": slot["starts_at"],
            "suggested_ends_at": slot["ends_at"],
        })

        await self.telegram.send_message(
            chat_id,
            f"Спасибо! Передал координатору: {session['specialty_name']}, "
            f"{slot['starts_at']}, филиал «{slot['branch_name']}». "
            "Ожидайте подтверждения.",
        )
        self._sessions.pop(chat_id, None)
