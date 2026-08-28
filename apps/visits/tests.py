from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import User
from apps.branches.models import Branch
from apps.patients.models import Patient

from .models import Visit, VisitStatus


class VisitTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.doctor = User.objects.create(username="doc")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

    def test_default_status_is_in_progress(self):
        visit = Visit.objects.create(patient=self.patient, doctor=self.doctor, branch=self.branch)
        self.assertEqual(visit.status, VisitStatus.IN_PROGRESS)
        self.assertIsNone(visit.closed_at)

    def test_close_sets_status_and_closed_at(self):
        visit = Visit.objects.create(patient=self.patient, doctor=self.doctor, branch=self.branch)
        visit.close()
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.COMPLETED)
        self.assertIsNotNone(visit.closed_at)
