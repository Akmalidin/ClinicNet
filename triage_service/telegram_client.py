"""Minimal Telegram Bot API client — long polling (getUpdates), not a
webhook: no public HTTPS endpoint/nginx routing needed for this first
cut (see the Phase 5 sub-module 2 recon — webhook mode is a documented,
straightforward follow-up, not required for the bot to work).
"""
from __future__ import annotations

import httpx

from . import config

API_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


class TelegramClient:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=35.0)
        self._offset = 0

    async def aclose(self):
        await self._client.aclose()

    async def get_updates(self) -> list[dict]:
        """Long-poll for up to 30s. Telegram holds the connection open
        until either a message arrives or the timeout elapses — this is
        the whole polling loop, no extra sleep needed between calls."""
        response = await self._client.get(
            f"{API_BASE}/getUpdates",
            params={"offset": self._offset, "timeout": 30, "allowed_updates": '["message"]'},
        )
        response.raise_for_status()
        result = response.json()["result"]
        if result:
            self._offset = result[-1]["update_id"] + 1
        return result

    async def send_message(self, chat_id: int, text: str, request_contact: bool = False):
        payload = {"chat_id": chat_id, "text": text}
        if request_contact:
            payload["reply_markup"] = {
                "keyboard": [[{"text": "Поделиться номером телефона", "request_contact": True}]],
                "resize_keyboard": True,
                "one_time_keyboard": True,
            }
        else:
            payload["reply_markup"] = {"remove_keyboard": True}
        response = await self._client.post(f"{API_BASE}/sendMessage", json=payload)
        response.raise_for_status()
        return response.json()
