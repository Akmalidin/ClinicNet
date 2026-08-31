from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission
from apps.patients.models import Patient

from .models import Admission, AdmissionStatus, Bed, BedStatus, Department, Room, StaffDepartmentAssignment, Transfer
from .permissions import HasDepartmentPermission
from .rbac import departments_for_permission
from .serializers import (
    AdmissionSerializer,
    BedSerializer,
    DepartmentSerializer,
    RoomSerializer,
    StaffDepartmentAssignmentSerializer,
    TransferSerializer,
)
from .services import admit_patient, discharge_admission, transfer_admission


def _validation_detail(exc: DjangoValidationError):
    return exc.message_dict if hasattr(exc, "message_dict") else exc.messages


class DepartmentViewSet(viewsets.ModelViewSet):
    """Ward structure management (coeчный fond layout) is a branch-level
    action, same tier as apps.branches management — deliberately uses the
    existing HasBranchPermission, NOT the new department-scoped
    permission class (that one is for patient data: Admission/
    ClinicalOrder/VitalsRecord, not for editing the ward layout itself).
    """

    serializer_class = DepartmentSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "inpatient.department.view",
        "POST": "inpatient.department.manage",
        "PUT": "inpatient.department.manage",
        "PATCH": "inpatient.department.manage",
        "DELETE": "inpatient.department.manage",
    }
    filterset_fields = ["branch", "is_active"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "inpatient.department.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return Department.objects.filter(branch__in=allowed_branches).select_related("branch")


class RoomViewSet(viewsets.ModelViewSet):
    serializer_class = RoomSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "inpatient.department.view",
        "POST": "inpatient.department.manage",
        "PUT": "inpatient.department.manage",
        "PATCH": "inpatient.department.manage",
        "DELETE": "inpatient.department.manage",
    }
    filterset_fields = ["department", "is_active"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "inpatient.department.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return Room.objects.filter(department__branch__in=allowed_branches).select_related(
            "department", "department__branch"
        )


class BedViewSet(viewsets.ModelViewSet):
    serializer_class = BedSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "inpatient.department.view",
        "POST": "inpatient.department.manage",
        "PUT": "inpatient.department.manage",
        "PATCH": "inpatient.department.manage",
        "DELETE": "inpatient.department.manage",
    }
    filterset_fields = ["room", "status"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "inpatient.department.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return Bed.objects.filter(room__department__branch__in=allowed_branches).select_related(
            "room", "room__department", "room__department__branch"
        )

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        """Manual bed-status transitions (free/cleaning/reserved) —
        OCCUPIED is deliberately rejected here: it's a side effect of
        admission, never a direct action (see Bed's model docstring)."""
        bed = self.get_object()
        new_status = request.data.get("status")
        if new_status == BedStatus.OCCUPIED:
            return Response(
                {"detail": "Статус «занята» выставляется автоматически при госпитализации, а не вручную."},
                status=400,
            )
        if new_status not in BedStatus.values:
            return Response({"detail": "Некорректный статус койки."}, status=400)
        if bed.status == BedStatus.OCCUPIED:
            return Response(
                {"detail": "Койка занята активной госпитализацией — сначала выписка или перевод."},
                status=400,
            )
        bed.status = new_status
        bed.save(update_fields=["status"])
        return Response(self.get_serializer(bed).data)


class StaffDepartmentAssignmentViewSet(viewsets.ModelViewSet):
    """Assigning staff to a department is a branch-management action
    (same permission tier as the ward structure itself), not something a
    nurse grants herself — hence HasBranchPermission/inpatient.department.
    manage here, not the department-scoped permission class."""

    serializer_class = StaffDepartmentAssignmentSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "inpatient.department.view",
        "POST": "inpatient.department.manage",
        "PUT": "inpatient.department.manage",
        "PATCH": "inpatient.department.manage",
        "DELETE": "inpatient.department.manage",
    }
    filterset_fields = ["staff", "department", "is_active"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "inpatient.department.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return StaffDepartmentAssignment.objects.filter(
            department__branch__in=allowed_branches
        ).select_related("staff", "department")


class AdmissionViewSet(viewsets.ModelViewSet):
    """Госпитализации, ограниченные отделениями, доступными пользователю
    (apps.inpatient.rbac.departments_for_permission) — department-scoped
    equivalent of Visit/Appointment's branch scoping, one level deeper.
    """

    serializer_class = AdmissionSerializer
    permission_classes = [HasDepartmentPermission]
    required_permission = {
        "GET": "inpatient.admission.view",
        "POST": "inpatient.admission.manage",
        "PUT": "inpatient.admission.manage",
        "PATCH": "inpatient.admission.manage",
        "DELETE": "inpatient.admission.manage",
    }
    filterset_fields = ["department", "bed", "patient", "status"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "inpatient.admission.view")
        allowed_departments = departments_for_permission(self.request.user, code)
        return Admission.objects.filter(department__in=allowed_departments).select_related(
            "patient", "department", "department__branch", "bed", "bed__room",
            "attending_doctor", "admitted_by",
        )

    def create(self, request, *args, **kwargs):
        """Bypasses the serializer's default create entirely — admission
        has a real side effect (occupying the bed) that has to happen
        atomically with the row itself, same reasoning as
        VisitViewSet.close() calling apps.inventory.services.
        consume_for_visit instead of a plain serializer.save(). Permission
        is checked against the TARGET department (there's no existing
        object yet for get_object() to resolve it from)."""
        data = request.data
        try:
            department = Department.objects.get(pk=data.get("department"))
        except (Department.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "Отделение не найдено."}, status=400)

        self.check_object_permissions(request, department)

        try:
            bed = Bed.objects.get(pk=data.get("bed"))
            patient = Patient.objects.get(pk=data.get("patient"))
            attending_doctor = User.objects.get(pk=data.get("attending_doctor"))
        except (Bed.DoesNotExist, Patient.DoesNotExist, User.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "Некорректные ссылки на койку/пациента/лечащего врача."}, status=400)

        try:
            admission = admit_patient(
                patient=patient,
                department=department,
                bed=bed,
                attending_doctor=attending_doctor,
                admitted_by=request.user,
                diagnosis_at_admission=data.get("diagnosis_at_admission", ""),
            )
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))

        return Response(self.get_serializer(admission).data, status=201)

    @action(detail=True, methods=["post"])
    def discharge(self, request, pk=None):
        admission = self.get_object()
        if admission.status != AdmissionStatus.ACTIVE:
            return Response({"detail": "Пациент уже выписан."}, status=400)
        discharge_admission(admission, epicrisis=request.data.get("discharge_epicrisis", ""))
        return Response(self.get_serializer(admission).data)

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        """Перевод — get_object() already confirmed the caller can act on
        the admission's CURRENT (source) department; the destination
        department is checked separately below, since a department-scoped
        actor (department-head/nurse) shouldn't be able to move a patient
        into a department they have no standing in either — a doctor/
        branch-admin with own_branch reach passes this trivially, same as
        the source check."""
        admission = self.get_object()

        try:
            to_department = Department.objects.get(pk=request.data.get("to_department"))
            to_bed = Bed.objects.get(pk=request.data.get("to_bed"))
        except (Department.DoesNotExist, Bed.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "Некорректные ссылки на отделение/койку назначения."}, status=400)

        self.check_object_permissions(request, to_department)

        try:
            transfer_admission(
                admission=admission,
                to_department=to_department,
                to_bed=to_bed,
                transferred_by=request.user,
                reason=request.data.get("reason", ""),
            )
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))

        admission.refresh_from_db()
        return Response(self.get_serializer(admission).data)


class TransferViewSet(viewsets.ReadOnlyModelViewSet):
    """Append-only перевод-лог — read-only, created only by
    AdmissionViewSet.transfer (apps.inpatient.services.transfer_admission),
    same shape as PaymentViewSet/StockMovementViewSet."""

    serializer_class = TransferSerializer
    permission_classes = [HasDepartmentPermission]
    required_permission = {"GET": "inpatient.admission.view"}
    filterset_fields = ["admission", "from_department", "to_department"]

    def get_queryset(self):
        allowed_departments = departments_for_permission(self.request.user, "inpatient.admission.view")
        # Both directions — a nurse who was in the FROM department should
        # still see the historic record of a patient who left it, not
        # only rows currently resolving to a department she's in now.
        return Transfer.objects.filter(
            Q(from_department__in=allowed_departments) | Q(to_department__in=allowed_departments)
        ).select_related("admission", "from_department", "from_bed", "to_department", "to_bed", "transferred_by")
