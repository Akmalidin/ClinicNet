from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, User, UserRole
from apps.branches.models import Branch
from apps.patients.models import Patient
from apps.referrals.models import Referral
from apps.visits.models import Visit

from .models import Appointment, AppointmentStatus


class AppointmentOverlapTests(TenantTestCase):
    """A doctor can't be double-booked, in the same branch or across branches
    (see apps.scheduling.models.Appointment.clean — this was a real bug
    caught during manual smoke testing: the first version scoped the
    overlap check to a single branch, which allowed a doctor to be
    "booked" at two branches at the same time).
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.doctor = User.objects.create(username="doc")
        self.other_doctor = User.objects.create(username="doc2")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.start = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

    def _appointment(self, **overrides):
        defaults = dict(
            branch=self.branch_a,
            patient=self.patient,
            doctor=self.doctor,
            starts_at=self.start,
            ends_at=self.start + timedelta(minutes=30),
            status=AppointmentStatus.SCHEDULED,
        )
        defaults.update(overrides)
        return Appointment(**defaults)

    def test_valid_appointment_passes(self):
        appt = self._appointment()
        appt.full_clean()  # should not raise

    def test_end_before_start_rejected(self):
        appt = self._appointment(ends_at=self.start - timedelta(minutes=30))
        with self.assertRaises(ValidationError):
            appt.full_clean()

    def test_same_branch_overlap_rejected(self):
        self._appointment().save()
        overlapping = self._appointment(
            starts_at=self.start + timedelta(minutes=15),
            ends_at=self.start + timedelta(minutes=45),
        )
        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_cross_branch_overlap_rejected(self):
        """Same doctor, same time slot, different branch -> still invalid:
        the doctor can't physically be in two branches at once."""
        self._appointment(branch=self.branch_a).save()
        overlapping = self._appointment(branch=self.branch_b)
        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_different_doctor_same_slot_is_fine(self):
        self._appointment(doctor=self.doctor).save()
        other = self._appointment(doctor=self.other_doctor)
        other.full_clean()  # should not raise

    def test_cancelled_appointment_does_not_block_slot(self):
        self._appointment(status=AppointmentStatus.CANCELLED).save()
        new_appt = self._appointment()
        new_appt.full_clean()  # should not raise: cancelled slots are free


class AppointmentReferralFieldAPITests(TenantTestCase):
    """The `referral` field AppointmentSerializer exposes — feeds
    ReferralBadge.vue's icon + tooltip on the schedule view (reason + who
    referred), so a receptionist/doctor can see at a glance that a booked
    appointment came from a referral, not a walk-in."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал", code="a")
        view_perm = Permission.objects.create(code="appointment.view", category="scheduling")
        role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=role, permission=view_perm)

        self.from_doctor = User.objects.create(username="from_doc", first_name="Иван", last_name="Иванов")
        self.to_doctor = User.objects.create(username="to_doc")
        self.viewer = User.objects.create(username="viewer")
        UserRole.objects.create(user=self.viewer, role=role, branch_scope=BranchScope.ALL)

        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.start = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.viewer)
        self.host = self.domain.domain

    def test_appointment_from_referral_exposes_it(self):
        visit = Visit.objects.create(
            patient=self.patient, doctor=self.from_doctor, branch=self.branch, reason="Осмотр",
        )
        referral = Referral.objects.create(
            patient=self.patient, from_doctor=self.from_doctor, to_doctor=self.to_doctor,
            from_branch=self.branch, to_branch=self.branch, source_visit=visit,
            reason="Ортодонтическая консультация",
        )
        appointment = Appointment.objects.create(
            branch=self.branch, patient=self.patient, doctor=self.to_doctor,
            starts_at=self.start, ends_at=self.start + timedelta(minutes=30),
        )
        referral.target_appointment = appointment
        referral.status = "scheduled"
        referral.save()

        response = self.client_api.get(f"/api/v1/appointments/{appointment.pk}/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["referral"],
            {"id": referral.id, "reason": "Ортодонтическая консультация", "from_doctor_name": "Иван Иванов"},
        )

    def test_walk_in_appointment_has_null_referral(self):
        appointment = Appointment.objects.create(
            branch=self.branch, patient=self.patient, doctor=self.to_doctor,
            starts_at=self.start, ends_at=self.start + timedelta(minutes=30),
        )
        response = self.client_api.get(f"/api/v1/appointments/{appointment.pk}/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["referral"])
