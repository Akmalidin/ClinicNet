from datetime import time, timedelta

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, User, UserRole
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
from apps.patients.models import Patient
from apps.visits.models import Visit, VisitStatus

from .models import ChurnRisk, ChurnRiskStatus
from .services import calculate_churn_risks


def _set_created_at(visit, when):
    Visit.objects.filter(pk=visit.pk).update(created_at=when)


class CalculateChurnRisksServiceTests(TenantTestCase):
    """Чек-лист Фазы 5, под-модуль 1: для пациента с 1 визитом эвристика
    не создаёт ложный алерт, повторный прогон не дублирует, возврат
    пациента закрывает алерт автоматически."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.doctor = User.objects.create(username="doc")
        self.now = timezone.now()

    def _completed_visit(self, patient, days_ago):
        visit = Visit.objects.create(
            patient=patient, doctor=self.doctor, branch=self.branch, status=VisitStatus.COMPLETED,
        )
        _set_created_at(visit, self.now - timedelta(days=days_ago))
        return visit

    def test_patient_with_one_visit_is_not_flagged(self):
        patient = Patient.objects.create(first_name="Один", last_name="Визит")
        self._completed_visit(patient, days_ago=200)
        result = calculate_churn_risks()
        self.assertEqual(result["created"], 0)
        self.assertEqual(ChurnRisk.objects.filter(patient=patient).count(), 0)

    def test_patient_with_no_visits_is_not_flagged(self):
        Patient.objects.create(first_name="Без", last_name="Визитов")
        result = calculate_churn_risks()
        self.assertEqual(result["created"], 0)

    def test_regular_patient_overdue_gets_flagged(self):
        # Visits roughly every 30 days, last one 100 days ago -> overdue.
        patient = Patient.objects.create(first_name="Регулярный", last_name="Пациентов")
        self._completed_visit(patient, days_ago=160)
        self._completed_visit(patient, days_ago=130)
        self._completed_visit(patient, days_ago=100)

        result = calculate_churn_risks()
        self.assertEqual(result["created"], 1)
        risk = ChurnRisk.objects.get(patient=patient)
        self.assertEqual(risk.avg_interval_days, 30.0)
        self.assertGreater(risk.days_overdue, 0)
        self.assertEqual(risk.status, ChurnRiskStatus.NEW)
        self.assertEqual(risk.branch, self.branch)

    def test_regular_patient_not_yet_overdue_is_not_flagged(self):
        patient = Patient.objects.create(first_name="Недавний", last_name="Пациентов")
        self._completed_visit(patient, days_ago=60)
        self._completed_visit(patient, days_ago=30)
        self._completed_visit(patient, days_ago=2)  # well within the ~30-day interval

        result = calculate_churn_risks()
        self.assertEqual(result["created"], 0)
        self.assertEqual(ChurnRisk.objects.filter(patient=patient).count(), 0)

    def test_cancelled_visits_are_excluded_from_the_heuristic(self):
        patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self._completed_visit(patient, days_ago=160)
        self._completed_visit(patient, days_ago=100)
        cancelled = Visit.objects.create(
            patient=patient, doctor=self.doctor, branch=self.branch, status=VisitStatus.CANCELLED,
        )
        _set_created_at(cancelled, self.now - timedelta(days=5))

        result = calculate_churn_risks()
        # If the cancelled visit counted, avg interval / overdue would be very different (and possibly not overdue at all).
        self.assertEqual(result["created"], 1)
        risk = ChurnRisk.objects.get(patient=patient)
        self.assertEqual(risk.avg_interval_days, 60.0)

    def test_rerun_updates_existing_alert_instead_of_duplicating(self):
        patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self._completed_visit(patient, days_ago=160)
        self._completed_visit(patient, days_ago=130)
        self._completed_visit(patient, days_ago=100)

        calculate_churn_risks()
        first_id = ChurnRisk.objects.get(patient=patient).pk

        result = calculate_churn_risks()
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(ChurnRisk.objects.filter(patient=patient).count(), 1)
        self.assertEqual(ChurnRisk.objects.get(patient=patient).pk, first_id)

    def test_patient_return_auto_reactivates_the_alert(self):
        patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self._completed_visit(patient, days_ago=160)
        self._completed_visit(patient, days_ago=130)
        self._completed_visit(patient, days_ago=100)
        calculate_churn_risks()
        self.assertEqual(ChurnRisk.objects.get(patient=patient).status, ChurnRiskStatus.NEW)

        # Patient comes back for a fresh visit.
        self._completed_visit(patient, days_ago=1)
        result = calculate_churn_risks()
        self.assertEqual(result["reactivated"], 1)
        self.assertEqual(ChurnRisk.objects.get(patient=patient).status, ChurnRiskStatus.REACTIVATED)

    def test_acknowledged_alert_also_gets_auto_reactivated_on_return(self):
        patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self._completed_visit(patient, days_ago=160)
        self._completed_visit(patient, days_ago=130)
        self._completed_visit(patient, days_ago=100)
        calculate_churn_risks()
        risk = ChurnRisk.objects.get(patient=patient)
        risk.acknowledge()

        self._completed_visit(patient, days_ago=1)
        calculate_churn_risks()
        risk.refresh_from_db()
        self.assertEqual(risk.status, ChurnRiskStatus.REACTIVATED)

    def test_dismissed_alert_is_not_touched_by_rerun(self):
        patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self._completed_visit(patient, days_ago=160)
        self._completed_visit(patient, days_ago=130)
        self._completed_visit(patient, days_ago=100)
        calculate_churn_risks()
        risk = ChurnRisk.objects.get(patient=patient)
        risk.dismiss()

        result = calculate_churn_risks()
        # A dismissed alert is terminal — the patient is still overdue,
        # so a fresh NEW alert is created instead of resurrecting the old one.
        self.assertEqual(result["created"], 1)
        self.assertEqual(ChurnRisk.objects.filter(patient=patient).count(), 2)
        risk.refresh_from_db()
        self.assertEqual(risk.status, ChurnRiskStatus.DISMISSED)  # untouched

    def test_same_day_visits_are_skipped_not_flagged(self):
        patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        v1 = Visit.objects.create(
            patient=patient, doctor=self.doctor, branch=self.branch, status=VisitStatus.COMPLETED,
        )
        v2 = Visit.objects.create(
            patient=patient, doctor=self.doctor, branch=self.branch, status=VisitStatus.COMPLETED,
        )
        _set_created_at(v1, self.now)
        _set_created_at(v2, self.now)
        result = calculate_churn_risks()
        self.assertEqual(result["skipped_degenerate"], 1)
        self.assertEqual(ChurnRisk.objects.filter(patient=patient).count(), 0)


class ChurnRiskModelTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.risk = ChurnRisk.objects.create(
            patient=self.patient, branch=self.branch, last_visit_date=timezone.now() - timedelta(days=100),
            avg_interval_days=30.0, days_overdue=70, risk_score=2.33,
        )

    def test_acknowledge_then_no_op_on_repeat(self):
        self.assertTrue(self.risk.acknowledge())
        self.assertFalse(self.risk.acknowledge())

    def test_dismiss_is_terminal(self):
        self.assertTrue(self.risk.dismiss())
        self.assertFalse(self.risk.dismiss())
        self.assertFalse(self.risk.acknowledge())

    def test_cannot_reopen_dismissed_alert(self):
        self.risk.dismiss()
        self.risk.status = ChurnRiskStatus.NEW
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.risk.full_clean()


class ChurnRiskAPIRBACTests(TenantTestCase):
    """Чек-лист: координатор/администратор филиала видит и обрабатывает
    свой филиал, врач — нет (нет явного гранта)."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

        view_perm = Permission.objects.create(code="churn.view", category="churn")
        manage_perm = Permission.objects.create(code="churn.manage", category="churn")

        reception_role = Role.objects.create(name="Администратор ресепшн", codename="receptionist")
        RolePermission.objects.create(role=reception_role, permission=view_perm)
        RolePermission.objects.create(role=reception_role, permission=manage_perm)

        doctor_role = Role.objects.create(name="Врач", codename="doctor")
        # Deliberately no churn.* grant.

        self.reception_a = User.objects.create(username="reception_a")
        UserRole.objects.create(user=self.reception_a, role=reception_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.reception_a, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.doctor = User.objects.create(username="doc")
        UserRole.objects.create(user=self.doctor, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.doctor, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.risk_a = ChurnRisk.objects.create(
            patient=self.patient, branch=self.branch_a, last_visit_date=timezone.now() - timedelta(days=100),
            avg_interval_days=30.0, days_overdue=70, risk_score=2.33,
        )
        other_patient = Patient.objects.create(first_name="Второй", last_name="Пациентов")
        self.risk_b = ChurnRisk.objects.create(
            patient=other_patient, branch=self.branch_b, last_visit_date=timezone.now() - timedelta(days=100),
            avg_interval_days=30.0, days_overdue=70, risk_score=2.33,
        )
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_receptionist_sees_only_own_branch(self):
        client = self._client_for(self.reception_a)
        response = client.get("/api/v1/churn-risks/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        branches_seen = {row["branch"] for row in response.data}
        self.assertEqual(branches_seen, {self.branch_a.pk})

    def test_doctor_cannot_view_churn_risks(self):
        client = self._client_for(self.doctor)
        response = client.get("/api/v1/churn-risks/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 403)

    def test_receptionist_acknowledges_alert(self):
        client = self._client_for(self.reception_a)
        response = client.post(f"/api/v1/churn-risks/{self.risk_a.pk}/acknowledge/", {}, HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], ChurnRiskStatus.ACKNOWLEDGED)

    def test_receptionist_cannot_acknowledge_other_branchs_alert(self):
        client = self._client_for(self.reception_a)
        response = client.post(f"/api/v1/churn-risks/{self.risk_b.pk}/acknowledge/", {}, HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 404)

    def test_dismiss_then_repeat_rejected(self):
        client = self._client_for(self.reception_a)
        first = client.post(f"/api/v1/churn-risks/{self.risk_a.pk}/dismiss/", {}, HTTP_HOST=self.host)
        self.assertEqual(first.status_code, 200, first.data)
        second = client.post(f"/api/v1/churn-risks/{self.risk_a.pk}/dismiss/", {}, HTTP_HOST=self.host)
        self.assertEqual(second.status_code, 400)
