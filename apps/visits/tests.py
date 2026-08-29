from datetime import time

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, User, UserRole
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
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


class VisitAPIBranchScopingTests(TenantTestCase):
    """VisitViewSet is branch-scoped like Appointment — NOT network-wide
    like Patient. An all-scope user sees a patient's full cross-branch
    history; a single-branch doctor only sees their own branch's visits.
    That's RBAC working as designed, distinct from the "карта = один
    филиал" bug fixed on PatientViewSet in slice 1.
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.patient = Patient.objects.create(first_name="Общий", last_name="Пациент")

        view_perm = Permission.objects.create(code="visit.view", category="visits")
        doctor_role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=doctor_role, permission=view_perm)
        admin_role = Role.objects.create(name="Администратор сети", codename="network-admin")
        RolePermission.objects.create(role=admin_role, permission=view_perm)

        self.doctor_a = User.objects.create(username="doc_a")
        UserRole.objects.create(user=self.doctor_a, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.doctor_a, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )

        self.network_admin = User.objects.create(username="net_admin")
        UserRole.objects.create(user=self.network_admin, role=admin_role, branch_scope=BranchScope.ALL)

        Visit.objects.create(patient=self.patient, doctor=self.doctor_a, branch=self.branch_a)
        Visit.objects.create(patient=self.patient, doctor=self.doctor_a, branch=self.branch_b)

        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_all_scope_user_sees_full_cross_branch_history(self):
        response = self._client_for(self.network_admin).get(
            f"/api/v1/visits/?patient={self.patient.pk}", HTTP_HOST=self.host
        )
        self.assertEqual(response.status_code, 200)
        branches = {row["branch"] for row in response.json()}
        self.assertEqual(branches, {self.branch_a.pk, self.branch_b.pk})

    def test_single_branch_doctor_sees_only_their_branch(self):
        response = self._client_for(self.doctor_a).get(
            f"/api/v1/visits/?patient={self.patient.pk}", HTTP_HOST=self.host
        )
        self.assertEqual(response.status_code, 200)
        branches = {row["branch"] for row in response.json()}
        self.assertEqual(branches, {self.branch_a.pk})
