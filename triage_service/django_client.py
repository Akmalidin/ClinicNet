"""Thin async client over the existing ClinicNet REST API — the triage
service never touches Postgres directly (see the read-replica discussion
in the Phase 5 sub-module 2 recon: no replica exists, and going through
Django keeps this service from needing its own copy of the multi-tenant
schema-routing/RBAC logic — Django stays the single gatekeeper to the
data, exactly like every other API client in the project).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx

from . import config


class DjangoClient:
    def __init__(self):
        self._client = httpx.AsyncClient(base_url=config.DJANGO_API_BASE_URL, timeout=15.0)
        self._access_token: str | None = None

    async def aclose(self):
        await self._client.aclose()

    async def _ensure_token(self):
        if self._access_token:
            return
        response = await self._client.post(
            "/api/v1/auth/token/",
            json={"username": config.DJANGO_SERVICE_USERNAME, "password": config.DJANGO_SERVICE_PASSWORD},
        )
        response.raise_for_status()
        self._access_token = response.json()["access"]

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        await self._ensure_token()
        response = await self._client.get(
            path, params=params, headers={"Authorization": f"Bearer {self._access_token}"}
        )
        if response.status_code == 401:
            # Token expired — SimpleJWT access tokens are short-lived;
            # get a fresh one once and retry, same as any other client would.
            self._access_token = None
            await self._ensure_token()
            response = await self._client.get(
                path, params=params, headers={"Authorization": f"Bearer {self._access_token}"}
            )
        response.raise_for_status()
        return response

    async def _post(self, path: str, json: dict) -> httpx.Response:
        await self._ensure_token()
        response = await self._client.post(
            path, json=json, headers={"Authorization": f"Bearer {self._access_token}"}
        )
        if response.status_code == 401:
            self._access_token = None
            await self._ensure_token()
            response = await self._client.post(
                path, json=json, headers={"Authorization": f"Bearer {self._access_token}"}
            )
        return response

    async def list_specialties(self) -> list[dict]:
        response = await self._get("/api/v1/specialties/")
        return response.json()

    async def list_doctors(self, specialty_code: str) -> list[dict]:
        response = await self._get("/api/v1/doctors/", params={"specialty": specialty_code})
        return response.json()

    async def available_slots(self, doctor_id: int, on_date: date) -> list[dict]:
        response = await self._get(
            "/api/v1/referrals/available_slots/",
            params={"doctor": doctor_id, "date": on_date.isoformat()},
        )
        return response.json()

    async def find_nearest_slot(self, specialty_code: str, horizon_days: int) -> dict | None:
        """Across every doctor with this specialty, in every branch they
        work at, the earliest free slot within `horizon_days` — this is
        the piece that reuses apps.referrals available_slots (Phase 2)
        rather than reimplementing the free/busy calculation, per the
        Phase 5 prompt's explicit instruction.

        available_slots itself now also filters out already-elapsed slots
        (fixed at the source after this PR shipped — the endpoint used to
        compute a day's shift window purely from weekday/hours with no
        notion of "now", caught live here, but it's a real bug for EVERY
        caller of that endpoint, not just this one, so the fix belongs
        there, not in this client — see apps.referrals.views.
        ReferralViewSet.available_slots). This filter stays anyway, as
        defense-in-depth against clock skew between this service and
        Django, and so this method doesn't quietly regress if the source
        fix is ever reverted.
        """
        doctors = await self.list_doctors(specialty_code)
        now = datetime.now(timezone.utc)
        best: dict | None = None
        today = date.today()
        for offset in range(horizon_days):
            on_date = today + timedelta(days=offset)
            for doctor in doctors:
                slots = await self.available_slots(doctor["id"], on_date)
                future_slots = [s for s in slots if _parse_iso(s["starts_at"]) > now]
                if not future_slots:
                    continue
                candidate = future_slots[0]
                if best is None or candidate["starts_at"] < best["starts_at"]:
                    best = {**candidate, "doctor": doctor["id"], "doctor_name": doctor.get("display_name")}
            if best is not None:
                # Found something on this day — no need to search further
                # days (a slot next week is never "nearer" than one today).
                break
        return best

    async def ingest_suggestion(self, payload: dict) -> dict:
        response = await self._post("/api/v1/triage-suggestions/", payload)
        response.raise_for_status()
        return response.json()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
