from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import Specialty, User
from apps.branches.models import Branch
from apps.patients.models import Patient

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
