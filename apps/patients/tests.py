from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import Permission, Role, RolePermission, User, UserRole, BranchScope
from apps.branches.models import Branch

from .models import Patient


class PatientCardIsNetworkWideTests(TenantTestCase):
    """Regression test for the Phase 2 recon finding: the patient CARD must
    be visible network-wide — only Visit/Appointment inside it should be
    branch-scoped, not the card itself (see apps.patients.views.PatientViewSet).
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        view_perm = Permission.objects.create(code="patient.view", category="patients")
        role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=role, permission=view_perm)

        self.doctor = User.objects.create(username="doc_a_only")
        self.doctor.set_password("pass12345")
        self.doctor.save()
        # own_branch scope, but the doctor is only ever staffed at branch_a —
        # this is exactly the case that used to lose visibility of branch_b patients.
        UserRole.objects.create(user=self.doctor, role=role, branch_scope=BranchScope.OWN_BRANCH)

        self.patient_a = Patient.objects.create(
            first_name="А", last_name="Пациентов", primary_branch=self.branch_a
        )
        self.patient_b = Patient.objects.create(
            first_name="Б", last_name="Пациентов", primary_branch=self.branch_b
        )

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.doctor)
        self.host = self.domain.domain

    def test_list_shows_patients_from_every_branch(self):
        response = self.client_api.get("/api/v1/patients/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()}
        self.assertEqual(ids, {self.patient_a.pk, self.patient_b.pk})

    def test_detail_of_other_branch_patient_is_not_404(self):
        response = self.client_api.get(
            f"/api/v1/patients/{self.patient_b.pk}/", HTTP_HOST=self.host
        )
        self.assertEqual(response.status_code, 200)
