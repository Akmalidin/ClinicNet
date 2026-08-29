from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import (
    BranchScope,
    Permission,
    Role,
    RolePermission,
    Specialty,
    User,
    UserRole,
)
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
from apps.notifications.models import Notification
from apps.patients.models import Patient
from apps.scheduling.models import Appointment, AppointmentStatus
from apps.visits.models import Visit

from .models import Referral, ReferralStatus


class ReferralValidationTests(TenantTestCase):
    """Model-level rules from ClinicNet-Referrals-Prompt.md section 2 and the
    Phase 2 manual-check list ("outcome_note обязателен" on decline).
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.from_doctor = User.objects.create(username="from_doc")
        self.to_doctor = User.objects.create(username="to_doc")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.ortho = Specialty.objects.create(name="Ортодонтия", code="ortho")

    def _referral(self, **overrides):
        defaults = dict(
            patient=self.patient,
            from_doctor=self.from_doctor,
            from_branch=self.branch_a,
            to_branch=self.branch_b,
            reason="Консультация",
        )
        defaults.update(overrides)
        return Referral(**defaults)

    def test_intra_branch_referral_is_valid(self):
        ref = self._referral(to_doctor=self.to_doctor, to_branch=self.branch_a)
        ref.full_clean()  # should not raise
        self.assertEqual(ref.from_branch_id, ref.to_branch_id)

    def test_cross_branch_referral_is_valid(self):
        ref = self._referral(to_doctor=self.to_doctor)
        ref.full_clean()  # should not raise
        self.assertNotEqual(ref.from_branch_id, ref.to_branch_id)

    def test_referral_by_specialty_without_doctor_is_valid(self):
        ref = self._referral(to_specialty=self.ortho)
        ref.full_clean()  # should not raise

    def test_neither_doctor_nor_specialty_is_rejected(self):
        ref = self._referral()
        with self.assertRaises(ValidationError):
            ref.full_clean()

    def test_declined_without_outcome_note_is_rejected(self):
        ref = self._referral(to_doctor=self.to_doctor, status=ReferralStatus.DECLINED)
        with self.assertRaises(ValidationError):
            ref.full_clean()

    def test_declined_with_outcome_note_is_valid(self):
        ref = self._referral(
            to_doctor=self.to_doctor,
            status=ReferralStatus.DECLINED,
            outcome_note="Нет свободных слотов",
        )
        ref.full_clean()  # should not raise

    def test_mark_completed(self):
        ref = self._referral(to_doctor=self.to_doctor)
        ref.full_clean()
        ref.save()
        ref.mark_completed("Приём проведён")
        ref.refresh_from_db()
        self.assertEqual(ref.status, ReferralStatus.COMPLETED)
        self.assertIsNotNone(ref.completed_at)
        self.assertEqual(ref.outcome_note, "Приём проведён")


class ReferralAPITests(TenantTestCase):
    """End-to-end over the real HTTP + RBAC + notification stack, matching
    the Phase 2 manual-check list: intra- and cross-branch referrals through
    to a scheduled Appointment, decline requiring outcome_note with a
    notification to from_doctor, and the Appointment-completed signal
    closing the referral automatically.
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        view_perm = Permission.objects.create(code="referrals.view", category="referrals")
        manage_perm = Permission.objects.create(code="referrals.manage", category="referrals")
        # Matches the real seed_rbac: a plain doctor role gets NEITHER
        # referrals.view NOR referrals.manage — "своё" (create/list/act on
        # from_doctor==me or to_doctor==me) works unconditionally via
        # HasReferralPermission's object-level bypass, no grant needed.
        # referrals.view/manage are the coordinator/network escalation —
        # see test_plain_doctor_does_not_see_branch_queue below and
        # CoordinatorQueueVisibilityTests for what those grants unlock.
        doctor_role = Role.objects.create(name="Врач", codename="doctor")

        view_only_role = Role.objects.create(name="Врач (только просмотр)", codename="doctor-view-only")
        RolePermission.objects.create(role=view_only_role, permission=view_perm)

        self.from_doctor = User.objects.create(username="from_doc")
        self.to_doctor = User.objects.create(username="to_doc")
        for user, branch in [(self.from_doctor, self.branch_a), (self.to_doctor, self.branch_b)]:
            UserRole.objects.create(user=user, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
            StaffBranchAssignment.objects.create(
                staff=user, branch=branch, weekday=Weekday.MONDAY,
                start_time=time(9, 0), end_time=time(17, 0),
            )

        # A recipient with ONLY referrals.view (no manage) — regression case
        # for the "own" bypass in HasReferralPermission (see permissions.py).
        self.view_only_doctor = User.objects.create(username="view_only_doc")
        UserRole.objects.create(
            user=self.view_only_doctor, role=view_only_role, branch_scope=BranchScope.OWN_BRANCH
        )
        StaffBranchAssignment.objects.create(
            staff=self.view_only_doctor, branch=self.branch_b, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )

        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_create_referral_notifies_recipient(self):
        client = self._client_for(self.from_doctor)
        response = client.post(
            "/api/v1/referrals/",
            {
                "patient": self.patient.pk,
                "to_doctor": self.to_doctor.pk,
                "from_branch": self.branch_a.pk,
                "to_branch": self.branch_b.pk,
                "reason": "Ортодонтическая консультация",
            },
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["from_doctor"], self.from_doctor.pk)  # set from request.user
        self.assertEqual(response.data["status"], ReferralStatus.PENDING)

        notification = Notification.objects.get(referral_id=response.data["id"])
        self.assertEqual(notification.recipient_id, self.to_doctor.pk)

    def test_diagnosis_snapshot_is_copied_from_source_visit_not_client(self):
        """"Снапшот, не живая ссылка" (Referral docstring) has to come from
        the server's read of source_visit at creation time — never from
        whatever a client sends, or a stale/forged snapshot could pass
        through untouched. Also covers the frontend's actual create call
        (ReferralModal.vue), which never sends diagnosis_snapshot at all."""
        visit = Visit.objects.create(
            patient=self.patient, doctor=self.from_doctor, branch=self.branch_a,
            reason="Осмотр", diagnosis_snapshot={"teeth": ["11", "21"], "note": "кариес"},
        )
        client = self._client_for(self.from_doctor)
        response = client.post(
            "/api/v1/referrals/",
            {
                "patient": self.patient.pk,
                "to_doctor": self.to_doctor.pk,
                "from_branch": self.branch_a.pk,
                "to_branch": self.branch_b.pk,
                "source_visit": visit.pk,
                "reason": "Ортодонтическая консультация",
                # Attempting to smuggle a different snapshot — must be ignored.
                "diagnosis_snapshot": {"teeth": ["forged"]},
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["diagnosis_snapshot"], visit.diagnosis_snapshot)

        # Later edits to the visit must NOT retroactively change the
        # referral's snapshot — that's the whole point of a snapshot.
        visit.diagnosis_snapshot = {"teeth": ["changed-after-referral"]}
        visit.save()
        referral = Referral.objects.get(pk=response.data["id"])
        self.assertEqual(referral.diagnosis_snapshot, {"teeth": ["11", "21"], "note": "кариес"})

    def test_create_by_specialty_sends_no_notification_yet(self):
        ortho = Specialty.objects.create(name="Ортодонтия", code="ortho")
        client = self._client_for(self.from_doctor)
        response = client.post(
            "/api/v1/referrals/",
            {
                "patient": self.patient.pk,
                "to_specialty": ortho.pk,
                "from_branch": self.branch_a.pk,
                "to_branch": self.branch_b.pk,
                "reason": "Нужен ортодонт",
            },
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(Notification.objects.filter(referral_id=response.data["id"]).exists())

    def test_schedule_action_success(self):
        referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.from_doctor, to_doctor=self.to_doctor,
            from_branch=self.branch_a, to_branch=self.branch_b, reason="Консультация",
        )
        appointment = Appointment.objects.create(
            branch=self.branch_b, patient=self.patient, doctor=self.to_doctor,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, minutes=30),
        )
        client = self._client_for(self.to_doctor)
        response = client.post(
            f"/api/v1/referrals/{referral.pk}/schedule/",
            {"target_appointment": appointment.pk},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        referral.refresh_from_db()
        self.assertEqual(referral.status, ReferralStatus.SCHEDULED)
        self.assertEqual(referral.target_appointment_id, appointment.pk)
        self.assertIsNotNone(referral.scheduled_at)

    def test_schedule_action_rejects_wrong_branch(self):
        referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.from_doctor, to_doctor=self.to_doctor,
            from_branch=self.branch_a, to_branch=self.branch_b, reason="Консультация",
        )
        wrong_branch_appointment = Appointment.objects.create(
            branch=self.branch_a, patient=self.patient, doctor=self.to_doctor,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, minutes=30),
        )
        client = self._client_for(self.to_doctor)
        response = client.post(
            f"/api/v1/referrals/{referral.pk}/schedule/",
            {"target_appointment": wrong_branch_appointment.pk},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)

    def test_decline_requires_outcome_note_and_notifies_sender(self):
        referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.from_doctor, to_doctor=self.to_doctor,
            from_branch=self.branch_a, to_branch=self.branch_b, reason="Консультация",
        )
        client = self._client_for(self.to_doctor)

        empty = client.post(f"/api/v1/referrals/{referral.pk}/decline/", {}, HTTP_HOST=self.host)
        self.assertEqual(empty.status_code, 400)

        response = client.post(
            f"/api/v1/referrals/{referral.pk}/decline/",
            {"outcome_note": "Нет свободных слотов на этой неделе"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        referral.refresh_from_db()
        self.assertEqual(referral.status, ReferralStatus.DECLINED)

        notification = Notification.objects.get(referral=referral)
        self.assertEqual(notification.recipient_id, self.from_doctor.pk)

    def test_own_bypass_lets_view_only_recipient_decline(self):
        """Regression test: HasReferralPermission's view-level check must
        not require referrals.manage up front, or a recipient who only
        holds referrals.view would be 403'd before the object-level "own"
        bypass ever runs."""
        referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.from_doctor, to_doctor=self.view_only_doctor,
            from_branch=self.branch_a, to_branch=self.branch_b, reason="Консультация",
        )
        client = self._client_for(self.view_only_doctor)
        response = client.post(
            f"/api/v1/referrals/{referral.pk}/decline/",
            {"outcome_note": "Не моя специализация"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_appointment_completed_signal_closes_referral(self):
        referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.from_doctor, to_doctor=self.to_doctor,
            from_branch=self.branch_a, to_branch=self.branch_b, reason="Консультация",
            status=ReferralStatus.SCHEDULED, scheduled_at=timezone.now(),
        )
        appointment = Appointment.objects.create(
            branch=self.branch_b, patient=self.patient, doctor=self.to_doctor,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, minutes=30),
        )
        referral.target_appointment = appointment
        referral.save(update_fields=["target_appointment"])

        appointment.status = AppointmentStatus.COMPLETED
        appointment.save()

        referral.refresh_from_db()
        self.assertEqual(referral.status, ReferralStatus.COMPLETED)
        self.assertIsNotNone(referral.completed_at)
        self.assertTrue(Notification.objects.filter(referral=referral, recipient=self.from_doctor).exists())

    def test_available_slots_excludes_busy_time(self):
        # to_doctor works Mondays 9:00-17:00 at branch_b (see setUp).
        next_monday = timezone.localdate()
        while next_monday.weekday() != 0:
            next_monday += timedelta(days=1)

        busy_start = timezone.make_aware(
            timezone.datetime.combine(next_monday, time(10, 0))
        )
        Appointment.objects.create(
            branch=self.branch_b, patient=self.patient, doctor=self.to_doctor,
            starts_at=busy_start, ends_at=busy_start + timedelta(minutes=30),
        )

        client = self._client_for(self.from_doctor)
        response = client.get(
            "/api/v1/referrals/available_slots/",
            {"doctor": self.to_doctor.pk, "date": next_monday.isoformat()},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        slots = response.json()
        self.assertTrue(len(slots) > 0)
        starts = {s["starts_at"] for s in slots}
        self.assertFalse(any("10:00:00" in s for s in starts))  # busy slot excluded

    def test_completed_referral_cannot_be_reopened(self):
        """Manual-check item 4: a terminal (COMPLETED/DECLINED) referral is
        truly immutable — no action can move it back to a non-terminal
        status."""
        referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.from_doctor, to_doctor=self.to_doctor,
            from_branch=self.branch_a, to_branch=self.branch_b, reason="Консультация",
            status=ReferralStatus.COMPLETED, completed_at=timezone.now(),
        )
        client = self._client_for(self.to_doctor)

        response = client.post(
            f"/api/v1/referrals/{referral.pk}/decline/",
            {"outcome_note": "Передумал"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)

        response = client.post(f"/api/v1/referrals/{referral.pk}/complete/", {}, HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 400)

        referral.refresh_from_db()
        self.assertEqual(referral.status, ReferralStatus.COMPLETED)

    def test_declined_referral_cannot_be_completed(self):
        referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.from_doctor, to_doctor=self.to_doctor,
            from_branch=self.branch_a, to_branch=self.branch_b, reason="Консультация",
            status=ReferralStatus.DECLINED, outcome_note="Не моя специализация",
        )
        client = self._client_for(self.to_doctor)
        response = client.post(f"/api/v1/referrals/{referral.pk}/complete/", {}, HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 400)
        referral.refresh_from_db()
        self.assertEqual(referral.status, ReferralStatus.DECLINED)

    def test_plain_doctor_does_not_see_branch_queue(self):
        """Manual-check item 5: a doctor without an elevated (coordinator/
        network) referrals.view grant sees only what they personally sent
        or received — not the whole branch/network queue. doctor_role in
        setUp grants neither referrals.view nor referrals.manage, matching
        the real seed_rbac."""
        other_patient = Patient.objects.create(first_name="Другой", last_name="Пациент")
        unrelated_referral = Referral.objects.create(
            patient=other_patient, from_doctor=self.to_doctor, to_doctor=None,
            to_specialty=Specialty.objects.create(name="Хирургия", code="surgery"),
            from_branch=self.branch_b, to_branch=self.branch_b,
            reason="Направление, к которому from_doctor не имеет отношения",
        )
        client = self._client_for(self.from_doctor)
        response = client.get("/api/v1/referrals/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()}
        self.assertNotIn(unrelated_referral.pk, ids)


class CoordinatorQueueVisibilityTests(TenantTestCase):
    """The referrals.view/referrals.manage escalation — a branch coordinator
    sees and can act on the WHOLE branch queue, not just their own, even
    though they're neither from_doctor nor to_doctor on most of it."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

        view_perm = Permission.objects.create(code="referrals.view", category="referrals")
        manage_perm = Permission.objects.create(code="referrals.manage", category="referrals")
        coordinator_role = Role.objects.create(name="Координатор филиала", codename="branch-admin")
        RolePermission.objects.create(role=coordinator_role, permission=view_perm)
        RolePermission.objects.create(role=coordinator_role, permission=manage_perm)

        self.doctor_a = User.objects.create(username="doc_a")
        self.doctor_b = User.objects.create(username="doc_b")

        self.coordinator = User.objects.create(username="coordinator_b")
        UserRole.objects.create(
            user=self.coordinator, role=coordinator_role, branch_scope=BranchScope.OWN_BRANCH
        )
        StaffBranchAssignment.objects.create(
            staff=self.coordinator, branch=self.branch_b, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )

        # Coordinator is neither from_doctor nor to_doctor on this one.
        self.referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.doctor_a, to_doctor=self.doctor_b,
            from_branch=self.branch_a, to_branch=self.branch_b,
            reason="Координатор не участвует лично",
        )
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_coordinator_sees_referral_in_their_branch_queue(self):
        response = self._client_for(self.coordinator).get("/api/v1/referrals/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()}
        self.assertIn(self.referral.pk, ids)

    def test_coordinator_can_decline_referral_not_personally_theirs(self):
        response = self._client_for(self.coordinator).post(
            f"/api/v1/referrals/{self.referral.pk}/decline/",
            {"outcome_note": "Врач в отпуске"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
