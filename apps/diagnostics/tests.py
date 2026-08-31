from datetime import time

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, User, UserRole
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
from apps.patients.models import Patient
from apps.visits.models import Visit

from .models import LabOrder, LabOrderStatus, LabResult


class LabOrderModelTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.doctor = User.objects.create(username="doc")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

    def _order(self, **overrides):
        defaults = dict(
            patient=self.patient, ordered_by=self.doctor, branch=self.branch, test_type="Общий анализ крови",
        )
        defaults.update(overrides)
        return LabOrder.objects.create(**defaults)

    def test_default_status_is_ordered(self):
        order = self._order()
        self.assertEqual(order.status, LabOrderStatus.ORDERED)

    def test_cancel_sets_status(self):
        order = self._order()
        self.assertTrue(order.cancel())
        order.refresh_from_db()
        self.assertEqual(order.status, LabOrderStatus.CANCELLED)

    def test_cancel_is_a_no_op_once_terminal(self):
        order = self._order()
        order.cancel()
        self.assertFalse(order.cancel())  # already cancelled — no-op, not an exception

    def test_cannot_reopen_completed_order(self):
        order = self._order(status=LabOrderStatus.COMPLETED)
        order.status = LabOrderStatus.ORDERED
        with self.assertRaises(ValidationError):
            order.full_clean()


class LabOrderAPITests(TenantTestCase):
    """End-to-end: order from a patient's card (optionally tied to a
    Visit), manual result entry by a possibly-different staff member,
    is_abnormal flag, and cancel — mirrors the Referral module's own
    manual-verification rigor (see apps.referrals.tests)."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        view_perm = Permission.objects.create(code="diagnostics.view", category="diagnostics")
        manage_perm = Permission.objects.create(code="diagnostics.manage", category="diagnostics")
        doctor_role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=doctor_role, permission=view_perm)
        RolePermission.objects.create(role=doctor_role, permission=manage_perm)

        self.doctor = User.objects.create(username="doc")
        UserRole.objects.create(user=self.doctor, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.doctor, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )

        # A different staff member ("ответственный сотрудник") in the same
        # branch — enters the result for an order they didn't place.
        self.lab_tech = User.objects.create(username="labtech")
        UserRole.objects.create(user=self.lab_tech, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.lab_tech, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )

        # Out of branch_a entirely — must not see/act on branch_a's orders.
        self.other_doctor = User.objects.create(username="other_doc")
        UserRole.objects.create(user=self.other_doctor, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.other_doctor, branch=self.branch_b, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )

        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch_a, reason="Осмотр",
        )
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_create_order_from_visit(self):
        client = self._client_for(self.doctor)
        response = client.post(
            "/api/v1/lab-orders/",
            {
                "patient": self.patient.pk,
                "branch": self.branch_a.pk,
                "source_visit": self.visit.pk,
                "test_type": "Общий анализ крови",
                "comment": "Натощак",
                "urgency": "urgent",
            },
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["ordered_by"], self.doctor.pk)  # set from request.user
        self.assertEqual(response.data["status"], LabOrderStatus.ORDERED)
        self.assertIsNone(response.data["result"])

    def test_other_branch_doctor_cannot_see_order(self):
        order = LabOrder.objects.create(
            patient=self.patient, ordered_by=self.doctor, branch=self.branch_a, test_type="ОАК",
        )
        client = self._client_for(self.other_doctor)
        response = client.get("/api/v1/lab-orders/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [])

        detail = client.get(f"/api/v1/lab-orders/{order.pk}/", HTTP_HOST=self.host)
        self.assertEqual(detail.status_code, 404)

    def test_result_entered_by_different_staff_member_closes_order(self):
        order = LabOrder.objects.create(
            patient=self.patient, ordered_by=self.doctor, branch=self.branch_a, test_type="ОАК",
        )
        client = self._client_for(self.lab_tech)
        response = client.post(
            f"/api/v1/lab-orders/{order.pk}/result/",
            {"result_text": "Лейкоциты 12.0 (норма 4-9)", "is_abnormal": True},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], LabOrderStatus.COMPLETED)
        self.assertEqual(response.data["result"]["entered_by"], self.lab_tech.pk)
        self.assertTrue(response.data["result"]["is_abnormal"])

        order.refresh_from_db()
        self.assertEqual(order.status, LabOrderStatus.COMPLETED)
        self.assertTrue(LabResult.objects.filter(order=order, is_abnormal=True).exists())

    def test_cannot_submit_a_second_result(self):
        order = LabOrder.objects.create(
            patient=self.patient, ordered_by=self.doctor, branch=self.branch_a, test_type="ОАК",
        )
        LabResult.objects.create(order=order, entered_by=self.doctor, result_text="норма")
        order.status = LabOrderStatus.COMPLETED
        order.save(update_fields=["status"])

        client = self._client_for(self.doctor)
        response = client.post(
            f"/api/v1/lab-orders/{order.pk}/result/",
            {"result_text": "повторно", "is_abnormal": False},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_order(self):
        order = LabOrder.objects.create(
            patient=self.patient, ordered_by=self.doctor, branch=self.branch_a, test_type="ОАК",
        )
        client = self._client_for(self.doctor)
        response = client.post(f"/api/v1/lab-orders/{order.pk}/cancel/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], LabOrderStatus.CANCELLED)

    def test_cannot_enter_result_on_cancelled_order(self):
        order = LabOrder.objects.create(
            patient=self.patient, ordered_by=self.doctor, branch=self.branch_a, test_type="ОАК",
        )
        order.cancel()
        client = self._client_for(self.doctor)
        response = client.post(
            f"/api/v1/lab-orders/{order.pk}/result/",
            {"result_text": "норма", "is_abnormal": False},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)
