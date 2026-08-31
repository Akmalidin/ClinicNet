from datetime import time

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, User, UserRole
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
from apps.patients.models import Patient

from .models import (
    Admission,
    AdmissionStatus,
    Bed,
    BedStatus,
    Department,
    Room,
    StaffDepartmentAssignment,
    Transfer,
)
from .services import admit_patient, discharge_admission, transfer_admission


class DepartmentHierarchyModelTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.department = Department.objects.create(branch=self.branch, name="Терапия", code="therapy")
        self.room = Room.objects.create(department=self.department, name="204")

    def test_bed_defaults_to_free(self):
        bed = Bed.objects.create(room=self.room, label="1")
        self.assertEqual(bed.status, BedStatus.FREE)

    def test_bed_branch_property_resolves_through_room_and_department(self):
        bed = Bed.objects.create(room=self.room, label="1")
        self.assertEqual(bed.branch, self.branch)
        self.assertEqual(bed.department, self.department)

    def test_duplicate_department_code_in_same_branch_rejected(self):
        with self.assertRaises(Exception):
            Department.objects.create(branch=self.branch, name="Терапия 2", code="therapy")

    def test_duplicate_bed_label_in_same_room_rejected(self):
        Bed.objects.create(room=self.room, label="1")
        with self.assertRaises(Exception):
            Bed.objects.create(room=self.room, label="1")


class AdmissionModelTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.department = Department.objects.create(branch=self.branch, name="Терапия", code="therapy")
        self.other_department = Department.objects.create(branch=self.branch, name="Хирургия", code="surgery")
        self.room = Room.objects.create(department=self.department, name="204")
        self.bed = Bed.objects.create(room=self.room, label="1")
        self.doctor = User.objects.create(username="doc")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

    def _admission(self, **overrides):
        kwargs = dict(
            patient=self.patient, department=self.department, bed=self.bed,
            attending_doctor=self.doctor, admitted_by=self.doctor,
            diagnosis_at_admission="ОРВИ",
        )
        kwargs.update(overrides)
        return Admission(**kwargs)

    def test_bed_must_belong_to_the_admissions_department(self):
        admission = self._admission(department=self.other_department)
        with self.assertRaises(ValidationError):
            admission.full_clean()

    def test_two_active_admissions_cannot_share_a_bed(self):
        first = self._admission()
        first.full_clean()
        first.save()
        second = self._admission(patient=Patient.objects.create(first_name="Второй", last_name="Пациентов"))
        with self.assertRaises(ValidationError):
            second.full_clean()

    def test_discharged_admission_freeing_the_bed_allows_a_new_one(self):
        first = self._admission()
        first.full_clean()
        first.save()
        first.discharge()
        second = self._admission(patient=Patient.objects.create(first_name="Второй", last_name="Пациентов"))
        second.full_clean()  # no clash — first is DISCHARGED, not ACTIVE

    def test_discharge_is_a_no_op_once_terminal(self):
        admission = self._admission()
        admission.full_clean()
        admission.save()
        self.assertTrue(admission.discharge())
        self.assertFalse(admission.discharge())

    def test_cannot_reopen_discharged_admission(self):
        admission = self._admission()
        admission.full_clean()
        admission.save()
        admission.discharge()
        admission.status = AdmissionStatus.ACTIVE
        with self.assertRaises(ValidationError):
            admission.full_clean()


class InpatientServicesTests(TenantTestCase):
    """apps.inpatient.services.admit_patient/discharge_admission — the
    atomic bed-occupation side effect (checklist: "занять/освободить
    койку через реальный запрос... одна койка не может быть занята
    двумя госпитализациями одновременно")."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.department = Department.objects.create(branch=self.branch, name="Терапия", code="therapy")
        self.room = Room.objects.create(department=self.department, name="204")
        self.bed = Bed.objects.create(room=self.room, label="1")
        self.doctor = User.objects.create(username="doc")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

    def test_admit_patient_occupies_the_bed(self):
        admit_patient(
            patient=self.patient, department=self.department, bed=self.bed,
            attending_doctor=self.doctor, admitted_by=self.doctor,
            diagnosis_at_admission="ОРВИ",
        )
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, BedStatus.OCCUPIED)

    def test_admit_patient_rejects_an_occupied_bed(self):
        admit_patient(
            patient=self.patient, department=self.department, bed=self.bed,
            attending_doctor=self.doctor, admitted_by=self.doctor,
            diagnosis_at_admission="ОРВИ",
        )
        other_patient = Patient.objects.create(first_name="Второй", last_name="Пациентов")
        with self.assertRaises(ValidationError):
            admit_patient(
                patient=other_patient, department=self.department, bed=self.bed,
                attending_doctor=self.doctor, admitted_by=self.doctor,
                diagnosis_at_admission="Другое",
            )

    def test_discharge_frees_the_bed(self):
        admission = admit_patient(
            patient=self.patient, department=self.department, bed=self.bed,
            attending_doctor=self.doctor, admitted_by=self.doctor,
            diagnosis_at_admission="ОРВИ",
        )
        discharge_admission(admission)
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, BedStatus.FREE)

    def test_discharge_no_op_does_not_touch_bed(self):
        admission = admit_patient(
            patient=self.patient, department=self.department, bed=self.bed,
            attending_doctor=self.doctor, admitted_by=self.doctor,
            diagnosis_at_admission="ОРВИ",
        )
        discharge_admission(admission)
        # Manually mark cleaning after discharge, then try discharging again
        self.bed.refresh_from_db()
        self.bed.status = BedStatus.CLEANING
        self.bed.save(update_fields=["status"])
        changed = discharge_admission(admission)
        self.assertFalse(changed)
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, BedStatus.CLEANING)  # untouched, not forced back to FREE


class DepartmentStructureAPIRBACTests(TenantTestCase):
    """Branch-level management of Department/Room/Bed — same
    HasBranchPermission shape as everything else branch-scoped."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        view_perm = Permission.objects.create(code="inpatient.department.view", category="inpatient")
        manage_perm = Permission.objects.create(code="inpatient.department.manage", category="inpatient")
        role = Role.objects.create(name="Администратор филиала", codename="branch-admin")
        RolePermission.objects.create(role=role, permission=view_perm)
        RolePermission.objects.create(role=role, permission=manage_perm)

        self.admin_a = User.objects.create(username="admin_a")
        UserRole.objects.create(user=self.admin_a, role=role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.admin_a, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_branch_admin_can_create_department_in_own_branch(self):
        client = self._client_for(self.admin_a)
        response = client.post(
            "/api/v1/departments/", {"branch": self.branch_a.pk, "name": "Терапия", "code": "therapy"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_branch_admin_cannot_create_department_in_other_branch(self):
        client = self._client_for(self.admin_a)
        response = client.post(
            "/api/v1/departments/", {"branch": self.branch_b.pk, "name": "Терапия", "code": "therapy"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_branch_admin_cannot_see_other_branchs_departments(self):
        Department.objects.create(branch=self.branch_a, name="Терапия", code="therapy")
        Department.objects.create(branch=self.branch_b, name="Хирургия", code="surgery")
        client = self._client_for(self.admin_a)
        response = client.get("/api/v1/departments/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        branches_seen = {row["branch"] for row in response.data}
        self.assertEqual(branches_seen, {self.branch_a.pk})

    def test_bed_set_status_rejects_direct_occupied(self):
        department = Department.objects.create(branch=self.branch_a, name="Терапия", code="therapy")
        room = Room.objects.create(department=department, name="204")
        bed = Bed.objects.create(room=room, label="1")
        client = self._client_for(self.admin_a)
        response = client.post(
            f"/api/v1/beds/{bed.pk}/set_status/", {"status": "occupied"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)

    def test_bed_set_status_allows_cleaning(self):
        department = Department.objects.create(branch=self.branch_a, name="Терапия", code="therapy")
        room = Room.objects.create(department=department, name="204")
        bed = Bed.objects.create(room=room, label="1")
        client = self._client_for(self.admin_a)
        response = client.post(
            f"/api/v1/beds/{bed.pk}/set_status/", {"status": "cleaning"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "cleaning")


class AdmissionAPIRBACTests(TenantTestCase):
    """Department-scoped RBAC via apps.inpatient.rbac — the checklist's
    core case: a ward nurse sees only her own department's patients, not
    the whole branch, and not another branch at all. Doctor/branch-admin
    keep full own-branch reach (documented design choice)."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.dept_therapy = Department.objects.create(branch=self.branch_a, name="Терапия", code="therapy")
        self.dept_surgery = Department.objects.create(branch=self.branch_a, name="Хирургия", code="surgery")
        self.room_therapy = Room.objects.create(department=self.dept_therapy, name="204")
        self.bed_therapy = Bed.objects.create(room=self.room_therapy, label="1")
        self.room_surgery = Room.objects.create(department=self.dept_surgery, name="301")
        self.bed_surgery = Bed.objects.create(room=self.room_surgery, label="1")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

        view_perm = Permission.objects.create(code="inpatient.admission.view", category="inpatient")
        manage_perm = Permission.objects.create(code="inpatient.admission.manage", category="inpatient")

        doctor_role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=doctor_role, permission=view_perm)
        RolePermission.objects.create(role=doctor_role, permission=manage_perm)

        nurse_role = Role.objects.create(name="Постовая медсестра", codename="nurse")
        RolePermission.objects.create(role=nurse_role, permission=view_perm)

        # Doctor: ordinary own_branch grant — sees the WHOLE branch's
        # departments, same as everywhere else in the project.
        self.doctor = User.objects.create(username="doc")
        UserRole.objects.create(user=self.doctor, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.doctor, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        # Nurse: SPECIFIC_BRANCHES with NO branches attached — reaches
        # nothing via ordinary branch scoping; visibility comes entirely
        # from StaffDepartmentAssignment below (the documented provisioning
        # convention from apps.inpatient.rbac).
        self.nurse = User.objects.create(username="nurse_therapy")
        UserRole.objects.create(user=self.nurse, role=nurse_role, branch_scope=BranchScope.SPECIFIC_BRANCHES)
        StaffDepartmentAssignment.objects.create(staff=self.nurse, department=self.dept_therapy)

        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_doctor_sees_admissions_across_departments_in_own_branch(self):
        admit_patient(
            patient=self.patient, department=self.dept_surgery, bed=self.bed_surgery,
            attending_doctor=self.doctor, admitted_by=self.doctor, diagnosis_at_admission="Аппендицит",
        )
        client = self._client_for(self.doctor)
        response = client.get("/api/v1/admissions/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_nurse_sees_only_her_own_department_not_another_in_same_branch(self):
        admit_patient(
            patient=self.patient, department=self.dept_therapy, bed=self.bed_therapy,
            attending_doctor=self.doctor, admitted_by=self.doctor, diagnosis_at_admission="ОРВИ",
        )
        other_patient = Patient.objects.create(first_name="Второй", last_name="Пациентов")
        admit_patient(
            patient=other_patient, department=self.dept_surgery, bed=self.bed_surgery,
            attending_doctor=self.doctor, admitted_by=self.doctor, diagnosis_at_admission="Аппендицит",
        )

        client = self._client_for(self.nurse)
        response = client.get("/api/v1/admissions/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        departments_seen = {row["department"] for row in response.data}
        self.assertEqual(departments_seen, {self.dept_therapy.pk})

    def test_nurse_without_manage_permission_cannot_discharge(self):
        admission = admit_patient(
            patient=self.patient, department=self.dept_therapy, bed=self.bed_therapy,
            attending_doctor=self.doctor, admitted_by=self.doctor, diagnosis_at_admission="ОРВИ",
        )
        client = self._client_for(self.nurse)
        response = client.post(
            f"/api/v1/admissions/{admission.pk}/discharge/", {}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_doctor_admits_patient_via_api_and_bed_becomes_occupied(self):
        client = self._client_for(self.doctor)
        response = client.post(
            "/api/v1/admissions/",
            {
                "patient": self.patient.pk, "department": self.dept_therapy.pk, "bed": self.bed_therapy.pk,
                "attending_doctor": self.doctor.pk, "diagnosis_at_admission": "ОРВИ",
            },
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], AdmissionStatus.ACTIVE)
        self.bed_therapy.refresh_from_db()
        self.assertEqual(self.bed_therapy.status, BedStatus.OCCUPIED)

    def test_double_booking_the_same_bed_via_api_is_rejected(self):
        client = self._client_for(self.doctor)
        first = client.post(
            "/api/v1/admissions/",
            {
                "patient": self.patient.pk, "department": self.dept_therapy.pk, "bed": self.bed_therapy.pk,
                "attending_doctor": self.doctor.pk, "diagnosis_at_admission": "ОРВИ",
            },
            HTTP_HOST=self.host,
        )
        self.assertEqual(first.status_code, 201, first.data)

        other_patient = Patient.objects.create(first_name="Второй", last_name="Пациентов")
        second = client.post(
            "/api/v1/admissions/",
            {
                "patient": other_patient.pk, "department": self.dept_therapy.pk, "bed": self.bed_therapy.pk,
                "attending_doctor": self.doctor.pk, "diagnosis_at_admission": "Другое",
            },
            HTTP_HOST=self.host,
        )
        self.assertEqual(second.status_code, 400)

    def test_discharge_via_api_frees_the_bed(self):
        client = self._client_for(self.doctor)
        create = client.post(
            "/api/v1/admissions/",
            {
                "patient": self.patient.pk, "department": self.dept_therapy.pk, "bed": self.bed_therapy.pk,
                "attending_doctor": self.doctor.pk, "diagnosis_at_admission": "ОРВИ",
            },
            HTTP_HOST=self.host,
        )
        admission_id = create.data["id"]

        discharge = client.post(
            f"/api/v1/admissions/{admission_id}/discharge/",
            {"discharge_epicrisis": "Выздоровление, выписан под наблюдение поликлиники."},
            HTTP_HOST=self.host,
        )
        self.assertEqual(discharge.status_code, 200, discharge.data)
        self.assertEqual(discharge.data["status"], AdmissionStatus.DISCHARGED)

        self.bed_therapy.refresh_from_db()
        self.assertEqual(self.bed_therapy.status, BedStatus.FREE)

        # Double-discharge — same "no silent duplicate" guard as
        # Invoice.pay/LabOrder.result/Visit.close.
        second = client.post(f"/api/v1/admissions/{admission_id}/discharge/", {}, HTTP_HOST=self.host)
        self.assertEqual(second.status_code, 400)

    def test_nurse_from_branch_b_sees_nothing(self):
        """Not just "not this department" — a different BRANCH entirely
        must be invisible too, same as every other branch-scoped resource
        in the project."""
        admit_patient(
            patient=self.patient, department=self.dept_therapy, bed=self.bed_therapy,
            attending_doctor=self.doctor, admitted_by=self.doctor, diagnosis_at_admission="ОРВИ",
        )
        nurse_role = Role.objects.get(codename="nurse")
        nurse_b = User.objects.create(username="nurse_b")
        UserRole.objects.create(user=nurse_b, role=nurse_role, branch_scope=BranchScope.SPECIFIC_BRANCHES)
        # No StaffDepartmentAssignment at all for nurse_b.

        client = self._client_for(nurse_b)
        response = client.get("/api/v1/admissions/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)


class TransferServiceTests(TenantTestCase):
    """apps.inpatient.services.transfer_admission — the checklist's
    "история переводов сохраняется, а не перезаписывается"."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.dept_therapy = Department.objects.create(branch=self.branch, name="Терапия", code="therapy")
        self.dept_surgery = Department.objects.create(branch=self.branch, name="Хирургия", code="surgery")
        self.room_t = Room.objects.create(department=self.dept_therapy, name="204")
        self.bed_t1 = Bed.objects.create(room=self.room_t, label="1")
        self.bed_t2 = Bed.objects.create(room=self.room_t, label="2")
        self.room_s = Room.objects.create(department=self.dept_surgery, name="301")
        self.bed_s1 = Bed.objects.create(room=self.room_s, label="1")
        self.doctor = User.objects.create(username="doc")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.admission = admit_patient(
            patient=self.patient, department=self.dept_therapy, bed=self.bed_t1,
            attending_doctor=self.doctor, admitted_by=self.doctor, diagnosis_at_admission="ОРВИ",
        )

    def test_transfer_moves_admission_and_frees_old_bed_occupies_new(self):
        transfer_admission(
            admission=self.admission, to_department=self.dept_surgery, to_bed=self.bed_s1,
            transferred_by=self.doctor, reason="Осложнение, требуется операция.",
        )
        self.admission.refresh_from_db()
        self.assertEqual(self.admission.department_id, self.dept_surgery.pk)
        self.assertEqual(self.admission.bed_id, self.bed_s1.pk)

        self.bed_t1.refresh_from_db()
        self.bed_s1.refresh_from_db()
        self.assertEqual(self.bed_t1.status, BedStatus.FREE)
        self.assertEqual(self.bed_s1.status, BedStatus.OCCUPIED)

    def test_transfer_creates_a_history_record_not_just_a_field_change(self):
        transfer_admission(
            admission=self.admission, to_department=self.dept_surgery, to_bed=self.bed_s1,
            transferred_by=self.doctor, reason="Осложнение.",
        )
        self.assertEqual(Transfer.objects.filter(admission=self.admission).count(), 1)
        record = Transfer.objects.get(admission=self.admission)
        self.assertEqual(record.from_department_id, self.dept_therapy.pk)
        self.assertEqual(record.from_bed_id, self.bed_t1.pk)
        self.assertEqual(record.to_department_id, self.dept_surgery.pk)
        self.assertEqual(record.to_bed_id, self.bed_s1.pk)

    def test_second_transfer_adds_another_history_row_not_overwrite(self):
        transfer_admission(
            admission=self.admission, to_department=self.dept_surgery, to_bed=self.bed_s1,
            transferred_by=self.doctor, reason="Операция.",
        )
        transfer_admission(
            admission=self.admission, to_department=self.dept_therapy, to_bed=self.bed_t2,
            transferred_by=self.doctor, reason="Долечивание.",
        )
        self.assertEqual(Transfer.objects.filter(admission=self.admission).count(), 2)
        self.admission.refresh_from_db()
        self.assertEqual(self.admission.bed_id, self.bed_t2.pk)

    def test_transfer_rejects_an_occupied_target_bed(self):
        other_patient = Patient.objects.create(first_name="Второй", last_name="Пациентов")
        admit_patient(
            patient=other_patient, department=self.dept_surgery, bed=self.bed_s1,
            attending_doctor=self.doctor, admitted_by=self.doctor, diagnosis_at_admission="Другое",
        )
        with self.assertRaises(ValidationError):
            transfer_admission(
                admission=self.admission, to_department=self.dept_surgery, to_bed=self.bed_s1,
                transferred_by=self.doctor,
            )
        # Nothing moved — original bed still occupied by the original admission.
        self.admission.refresh_from_db()
        self.assertEqual(self.admission.bed_id, self.bed_t1.pk)

    def test_transfer_rejects_bed_not_belonging_to_target_department(self):
        with self.assertRaises(ValidationError):
            transfer_admission(
                admission=self.admission, to_department=self.dept_surgery, to_bed=self.bed_t2,
                transferred_by=self.doctor,
            )

    def test_transfer_rejects_discharged_admission(self):
        discharge_admission(self.admission)
        with self.assertRaises(ValidationError):
            transfer_admission(
                admission=self.admission, to_department=self.dept_surgery, to_bed=self.bed_s1,
                transferred_by=self.doctor,
            )


class TransferAPIRBACTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.dept_therapy = Department.objects.create(branch=self.branch, name="Терапия", code="therapy")
        self.dept_surgery = Department.objects.create(branch=self.branch, name="Хирургия", code="surgery")
        self.room_t = Room.objects.create(department=self.dept_therapy, name="204")
        self.bed_t1 = Bed.objects.create(room=self.room_t, label="1")
        self.room_s = Room.objects.create(department=self.dept_surgery, name="301")
        self.bed_s1 = Bed.objects.create(room=self.room_s, label="1")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

        view_perm = Permission.objects.create(code="inpatient.admission.view", category="inpatient")
        manage_perm = Permission.objects.create(code="inpatient.admission.manage", category="inpatient")
        doctor_role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=doctor_role, permission=view_perm)
        RolePermission.objects.create(role=doctor_role, permission=manage_perm)

        nurse_role = Role.objects.create(name="Постовая медсестра", codename="nurse")
        RolePermission.objects.create(role=nurse_role, permission=view_perm)

        self.doctor = User.objects.create(username="doc")
        UserRole.objects.create(user=self.doctor, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.doctor, branch=self.branch, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.nurse_therapy = User.objects.create(username="nurse_therapy")
        UserRole.objects.create(
            user=self.nurse_therapy, role=nurse_role, branch_scope=BranchScope.SPECIFIC_BRANCHES
        )
        StaffDepartmentAssignment.objects.create(staff=self.nurse_therapy, department=self.dept_therapy)

        self.admission = admit_patient(
            patient=self.patient, department=self.dept_therapy, bed=self.bed_t1,
            attending_doctor=self.doctor, admitted_by=self.doctor, diagnosis_at_admission="ОРВИ",
        )
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_doctor_transfers_via_api(self):
        client = self._client_for(self.doctor)
        response = client.post(
            f"/api/v1/admissions/{self.admission.pk}/transfer/",
            {"to_department": self.dept_surgery.pk, "to_bed": self.bed_s1.pk, "reason": "Операция."},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["department"], self.dept_surgery.pk)
        self.bed_t1.refresh_from_db()
        self.bed_s1.refresh_from_db()
        self.assertEqual(self.bed_t1.status, BedStatus.FREE)
        self.assertEqual(self.bed_s1.status, BedStatus.OCCUPIED)

    def test_nurse_without_manage_permission_cannot_transfer(self):
        client = self._client_for(self.nurse_therapy)
        response = client.post(
            f"/api/v1/admissions/{self.admission.pk}/transfer/",
            {"to_department": self.dept_surgery.pk, "to_bed": self.bed_s1.pk},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_nurse_sees_transfer_history_for_her_department_even_after_patient_leaves(self):
        client_doctor = self._client_for(self.doctor)
        client_doctor.post(
            f"/api/v1/admissions/{self.admission.pk}/transfer/",
            {"to_department": self.dept_surgery.pk, "to_bed": self.bed_s1.pk, "reason": "Операция."},
            HTTP_HOST=self.host,
        )
        client_nurse = self._client_for(self.nurse_therapy)
        response = client_nurse.get("/api/v1/transfers/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["from_department"], self.dept_therapy.pk)
        self.assertEqual(response.data[0]["to_department"], self.dept_surgery.pk)
