"""Standalone unit tests for the parts of triage_service that don't need
a live Telegram/Django round-trip — run from the REPO ROOT (triage_service
is a plain package, not a Django app, so this isn't `manage.py test`):
    python -m unittest triage_service.tests -v

The actual end-to-end path (classify -> find_nearest_slot -> ingest ->
coordinator confirm -> real Appointment) is proven against a real running
Django server, not here — see the Phase 5 sub-module 2 PR description
for that live-verification record; this sandbox's egress policy blocks
api.telegram.org outright, so there is no way to also exercise the
literal Telegram transport from an automated test in this repo.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from .classifier import KeywordSpecialtyClassifier
from .django_client import DjangoClient

SPECIALTIES = [
    {"id": 1, "name": "Терапевт", "code": "therapy"},
    {"id": 2, "name": "Ортодонт", "code": "ortho"},
]


class KeywordSpecialtyClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = KeywordSpecialtyClassifier()

    def test_matches_a_known_symptom(self):
        self.assertEqual(self.classifier.classify("Болит зуб, кариес наверное", SPECIALTIES), "therapy")

    def test_matches_orthodontics(self):
        self.assertEqual(self.classifier.classify("Хочу поставить брекеты", SPECIALTIES), "ortho")

    def test_no_match_returns_none(self):
        self.assertIsNone(self.classifier.classify("Просто хотел спросить про часы работы", SPECIALTIES))

    def test_never_returns_a_specialty_the_clinic_does_not_have(self):
        # "удаление" keyword maps to "surgery" in KEYWORD_MAP, but this
        # network's catalog only has therapy/ortho — must not hallucinate it.
        self.assertIsNone(self.classifier.classify("Нужно удалить зуб мудрости", SPECIALTIES))


class FindNearestSlotSkipsPastTests(unittest.IsolatedAsyncioTestCase):
    """Caught live (not by an earlier unit test — there wasn't one yet):
    apps.referrals available_slots computes a day's shift window purely
    from weekday/hours, with no notion of "now" — querying TODAY can
    hand back a slot that already elapsed. find_nearest_slot must filter
    those out itself rather than trust every row it gets back."""

    async def asyncSetUp(self):
        self.client = DjangoClient.__new__(DjangoClient)  # skip __init__'s httpx.AsyncClient/config access
        self.client.list_doctors = AsyncMock(return_value=[{"id": 1, "display_name": "Иван Петров"}])

    async def test_past_slot_today_is_skipped_in_favor_of_a_future_one(self):
        now = datetime.now(timezone.utc)
        past_slot = {
            "branch": 1, "branch_name": "Филиал А",
            "starts_at": (now - timedelta(hours=2)).isoformat(),
            "ends_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
        }
        future_slot = {
            "branch": 1, "branch_name": "Филиал А",
            "starts_at": (now + timedelta(hours=3)).isoformat(),
            "ends_at": (now + timedelta(hours=3, minutes=30)).isoformat(),
        }

        async def fake_available_slots(doctor_id, on_date):
            return [past_slot, future_slot] if on_date == now.date() else []

        self.client.available_slots = fake_available_slots
        result = await self.client.find_nearest_slot("therapy", horizon_days=3)
        self.assertEqual(result["starts_at"], future_slot["starts_at"])

    async def test_all_slots_past_falls_through_to_a_later_day(self):
        now = datetime.now(timezone.utc)
        today_past_slot = {
            "branch": 1, "branch_name": "Филиал А",
            "starts_at": (now - timedelta(hours=2)).isoformat(),
            "ends_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
        }
        tomorrow_slot = {
            "branch": 1, "branch_name": "Филиал А",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=1, minutes=30)).isoformat(),
        }

        async def fake_available_slots(doctor_id, on_date):
            if on_date == now.date():
                return [today_past_slot]
            if on_date == (now + timedelta(days=1)).date():
                return [tomorrow_slot]
            return []

        self.client.available_slots = fake_available_slots
        result = await self.client.find_nearest_slot("therapy", horizon_days=3)
        self.assertEqual(result["starts_at"], tomorrow_slot["starts_at"])


if __name__ == "__main__":
    unittest.main()
