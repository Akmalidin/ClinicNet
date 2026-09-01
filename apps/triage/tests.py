from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, Specialty, User, UserRole
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
from apps.patients.models import Patient
from apps.scheduling.models import Appointment, AppointmentStatus

from .models import TriageSuggestion, TriageSuggestionStatus
from .serializers import TriageSuggestionSerializer


def _future(hours):
    return timezone.now() + timedelta(hours=hours)


class TriageSuggestionModelTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.specialty = Specialty.objects.create(name="Ортодонтия", code="ortho")
        self.doctor = User.objects.create(username="doc")
        self.coordinator = User.objects.create(username="coordinator")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов", phone="+998900000000")

    def _suggestion(self, starts_in_hours=48):
        return TriageSuggestion.objects.create(
            external_chat_id="12345", contact_name="Иван", contact_phone="+998900000000",
            symptom_text="Болит зуб мудрости",
            matched_specialty=self.specialty, branch=self.branch, suggested_doctor=self.doctor,
            suggested_starts_at=_future(starts_in_hours), suggested_ends_at=_future(starts_in_hours + 1),
        )

    def test_confirm_creates_an_appointment(self):
        suggestion = self._suggestion()
        self.assertTrue(suggestion.confirm(confirmed_by=self.coordinator, patient=self.patient))
        self.assertEqual(suggestion.status, TriageSuggestionStatus.CONFIRMED)
        self.assertIsNotNone(suggestion.resulting_appointment)
        appt = suggestion.resulting_appointment
        self.assertEqual(appt.patient, self.patient)
        self.assertEqual(appt.doctor, self.doctor)
        self.assertEqual(appt.branch, self.branch)
        self.assertEqual(appt.status, AppointmentStatus.SCHEDULED)

    def test_confirm_is_a_no_op_once_terminal(self):
        suggestion = self._suggestion()
        suggestion.confirm(confirmed_by=self.coordinator, patient=self.patient)
        self.assertFalse(suggestion.confirm(confirmed_by=self.coordinator, patient=self.patient))

    def test_reject_is_terminal(self):
        suggestion = self._suggestion()
        self.assertTrue(suggestion.reject("Пациент передумал"))
        self.assertFalse(suggestion.reject())
        self.assertFalse(suggestion.confirm(confirmed_by=self.coordinator, patient=self.patient))

    def test_confirm_on_expired_slot_marks_expired_instead_of_booking(self):
        suggestion = self._suggestion(starts_in_hours=-1)  # already in the past
        self.assertFalse(suggestion.confirm(confirmed_by=self.coordinator, patient=self.patient))
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, TriageSuggestionStatus.EXPIRED)
        self.assertIsNone(suggestion.resulting_appointment)

    def test_confirm_rejects_if_slot_was_taken_in_the_meantime(self):
        """The same double-booking guard Appointment.clean() already
        has — re-validated at confirm time, not just at suggestion time."""
        suggestion = self._suggestion()
        other_patient = Patient.objects.create(first_name="Второй", last_name="Пациентов")
        Appointment.objects.create(
            branch=self.branch, patient=other_patient, doctor=self.doctor,
            starts_at=suggestion.suggested_starts_at, ends_at=suggestion.suggested_ends_at,
        )
        with self.assertRaises(ValidationError):
            suggestion.confirm(confirmed_by=self.coordinator, patient=self.patient)

    def test_cannot_reopen_confirmed_suggestion(self):
        suggestion = self._suggestion()
        suggestion.confirm(confirmed_by=self.coordinator, patient=self.patient)
        suggestion.status = TriageSuggestionStatus.PENDING
        with self.assertRaises(ValidationError):
            suggestion.full_clean()


class TriageSuggestionAPIRBACTests(TenantTestCase):
    """Ключевой сценарий: сервисный аккаунт бота создаёт предложение
    (ingest), координатор его подтверждает (не бот бронирует напрямую),
    врач без явного гранта доступа не имеет."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.specialty = Specialty.objects.create(name="Ортодонтия", code="ortho")
        self.doctor = User.objects.create(username="doc")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

        ingest_perm = Permission.objects.create(code="triage.ingest", category="triage")
        view_perm = Permission.objects.create(code="triage.view", category="triage")
        manage_perm = Permission.objects.create(code="triage.manage", category="triage")

        bot_role = Role.objects.create(name="AI-триаж бот", codename="triage-bot")
        RolePermission.objects.create(role=bot_role, permission=ingest_perm)

        coordinator_role = Role.objects.create(name="Администратор ресепшн", codename="receptionist")
        RolePermission.objects.create(role=coordinator_role, permission=view_perm)
        RolePermission.objects.create(role=coordinator_role, permission=manage_perm)

        doctor_role = Role.objects.create(name="Врач", codename="doctor")
        # Deliberately no triage.* grant.

        self.bot = User.objects.create(username="triage_bot_service")
        UserRole.objects.create(user=self.bot, role=bot_role, branch_scope=BranchScope.ALL)

        self.coordinator_a = User.objects.create(username="coordinator_a")
        UserRole.objects.create(
            user=self.coordinator_a, role=coordinator_role, branch_scope=BranchScope.OWN_BRANCH
        )
        StaffBranchAssignment.objects.create(
            staff=self.coordinator_a, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.doc_user = User.objects.create(username="doc_user")
        UserRole.objects.create(user=self.doc_user, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.doc_user, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _ingest_payload(self, branch):
        return {
            "external_chat_id": "555",
            "contact_name": "Пациент Telegram",
            "contact_phone": "+998900000001",
            "symptom_text": "Болит зуб",
            "matched_specialty": self.specialty.pk,
            "branch": branch.pk,
            "suggested_doctor": self.doctor.pk,
            "suggested_starts_at": _future(24).isoformat(),
            "suggested_ends_at": _future(25).isoformat(),
        }

    def test_bot_can_ingest_a_suggestion_for_any_branch(self):
        client = self._client_for(self.bot)
        response = client.post("/api/v1/triage-suggestions/", self._ingest_payload(self.branch_b), HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], TriageSuggestionStatus.PENDING)

    def test_coordinator_cannot_ingest(self):
        client = self._client_for(self.coordinator_a)
        response = client.post("/api/v1/triage-suggestions/", self._ingest_payload(self.branch_a), HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 403)

    def test_doctor_cannot_view_queue(self):
        client = self._client_for(self.doc_user)
        response = client.get("/api/v1/triage-suggestions/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 403)

    def test_coordinator_sees_only_own_branch(self):
        bot_client = self._client_for(self.bot)
        bot_client.post("/api/v1/triage-suggestions/", self._ingest_payload(self.branch_a), HTTP_HOST=self.host)
        bot_client.post("/api/v1/triage-suggestions/", self._ingest_payload(self.branch_b), HTTP_HOST=self.host)

        client = self._client_for(self.coordinator_a)
        response = client.get("/api/v1/triage-suggestions/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        branches_seen = {row["branch"] for row in response.data}
        self.assertEqual(branches_seen, {self.branch_a.pk})

    def test_coordinator_confirms_with_explicit_patient(self):
        bot_client = self._client_for(self.bot)
        create = bot_client.post(
            "/api/v1/triage-suggestions/", self._ingest_payload(self.branch_a), HTTP_HOST=self.host,
        )
        suggestion_id = create.data["id"]

        client = self._client_for(self.coordinator_a)
        response = client.post(
            f"/api/v1/triage-suggestions/{suggestion_id}/confirm/", {"patient": self.patient.pk},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], TriageSuggestionStatus.CONFIRMED)
        self.assertIsNotNone(response.data["resulting_appointment"])

    def test_confirm_without_patient_is_rejected(self):
        bot_client = self._client_for(self.bot)
        create = bot_client.post(
            "/api/v1/triage-suggestions/", self._ingest_payload(self.branch_a), HTTP_HOST=self.host,
        )
        suggestion_id = create.data["id"]
        client = self._client_for(self.coordinator_a)
        response = client.post(f"/api/v1/triage-suggestions/{suggestion_id}/confirm/", {}, HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 400)

    def test_coordinator_rejects_a_suggestion(self):
        bot_client = self._client_for(self.bot)
        create = bot_client.post(
            "/api/v1/triage-suggestions/", self._ingest_payload(self.branch_a), HTTP_HOST=self.host,
        )
        suggestion_id = create.data["id"]
        client = self._client_for(self.coordinator_a)
        response = client.post(
            f"/api/v1/triage-suggestions/{suggestion_id}/reject/", {"reason": "Пациент отменил"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], TriageSuggestionStatus.REJECTED)

    def test_matched_patient_candidate_hints_but_does_not_auto_link(self):
        existing = Patient.objects.create(first_name="Уже", last_name="Есть", phone="+998900000001")
        suggestion = TriageSuggestion.objects.create(
            external_chat_id="555", contact_name="X", contact_phone="+998900000001",
            symptom_text="X", matched_specialty=self.specialty, branch=self.branch_a,
            suggested_doctor=self.doctor, suggested_starts_at=_future(24), suggested_ends_at=_future(25),
        )
        data = TriageSuggestionSerializer(suggestion).data
        self.assertEqual(data["matched_patient_candidate"]["id"], existing.pk)
        self.assertIsNone(data["patient"])  # still not linked until explicit confirm
