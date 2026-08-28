from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import User
from apps.branches.models import Branch
from apps.patients.models import Patient

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
