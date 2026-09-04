from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import mixins
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission
from apps.patients.models import Patient

from .models import (
    Admission,
    AdmissionReason,
    AdmissionStatus,
    Bed,
    BedStatus,
    ClinicalOrder,
    ClinicalOrderStatus,
    Department,
    Operation,
    OperatingRoom,
    OperationStatus,
    Room,
    StaffDepartmentAssignment,
    Transfer,
    VitalsRecord,
)
from .permissions import HasDepartmentPermission
from .rbac import departments_for_permission
from .serializers import (
    AdmissionSerializer,
    BedSerializer,
    ClinicalOrderSerializer,
    DepartmentSerializer,
    OperatingRoomSerializer,
    OperationSerializer,
    RoomSerializer,
    StaffDepartmentAssignmentSerializer,
    TransferSerializer,
    VitalsRecordSerializer,
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
                reason=data.get("reason") or AdmissionReason.PLANNED,
                notes=data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))

        return Response(self.get_serializer(admission).data, status=201)

    @action(detail=False, methods=["get"], required_permission="inpatient.admission.manage")
    def intake_options(self, request):
        """Отделения → палаты → койки (со статусом каждой), доступные
        текущему пользователю для госпитализации — то, чего не хватало
        для «Приёма в стационар» из макета admissionintake.html.
        Специально НЕ переиспользует DepartmentViewSet/RoomViewSet/
        BedViewSet: те branch-scoped (HasBranchPermission через
        inpatient.department.view), а зав.отделением/медсестра
        видят СВОИ отделения только через StaffDepartmentAssignment
        (department-scoped, apps.inpatient.rbac) — через branch-scoped
        вьюсеты они не найдут даже собственную палату, если у их роли
        нет отдельного branch-уровневого гранта на inpatient.department.
        view (см. seed_rbac.py: "department-head"/"nurse" — SPECIFIC_
        BRANCHES без филиалов). Список кроватей — не только свободные:
        координатору нужно видеть и почему конкретная недоступна
        (занята/уборка/резерв), не только пустой список без объяснения.
        """
        departments = departments_for_permission(
            request.user, "inpatient.admission.manage"
        ).select_related("branch")
        rooms = Room.objects.filter(department__in=departments, is_active=True).select_related("department")
        beds = Bed.objects.filter(room__in=rooms).order_by("label")

        beds_by_room = {}
        for bed in beds:
            beds_by_room.setdefault(bed.room_id, []).append(
                {"id": bed.pk, "label": bed.label, "status": bed.status}
            )
        rooms_by_department = {}
        for room in rooms:
            rooms_by_department.setdefault(room.department_id, []).append(
                {"id": room.pk, "name": room.name, "beds": beds_by_room.get(room.pk, [])}
            )

        data = [
            {
                "id": department.pk,
                "name": department.name,
                "branch": department.branch_id,
                "branch_name": department.branch.name,
                "rooms": rooms_by_department.get(department.pk, []),
            }
            for department in departments
        ]
        return Response(data)

    @action(detail=False, methods=["get"], required_permission="inpatient.admission.view")
    def bed_board(self, request):
        """Коечный фонд (bedmanagement.html) — та же department-scoped
        разведка/структура, что intake_options, но на .view (шире круг:
        координатор/врач/медсестра, которым нужно просто видеть
        занятость, не обязательно госпитализировать). Занятая койка
        несёт настоящего пациента текущей активной госпитализации — в
        макете там ФИО, для резерва — время/повод («Плановая, 14:00»);
        последнего в модели нет вообще (Bed.status=RESERVED — просто
        ручная пометка персонала без данных о том, для кого/когда, см.
        Bed's докстринг), поэтому честно не показываем то, чего нет,
        вместо выдумывания.
        """
        departments = departments_for_permission(
            request.user, "inpatient.admission.view"
        ).select_related("branch")
        rooms = Room.objects.filter(department__in=departments, is_active=True).select_related("department")
        beds = Bed.objects.filter(room__in=rooms).order_by("label")

        active_admission_by_bed = {
            admission.bed_id: admission
            for admission in Admission.objects.filter(
                bed__in=beds, status=AdmissionStatus.ACTIVE
            ).select_related("patient")
        }

        beds_by_room = {}
        occupancy = {choice: 0 for choice in BedStatus.values}
        for bed in beds:
            occupancy[bed.status] += 1
            active_admission = active_admission_by_bed.get(bed.pk)
            beds_by_room.setdefault(bed.room_id, []).append({
                "id": bed.pk, "label": bed.label, "status": bed.status,
                "patient_name": str(active_admission.patient) if active_admission else None,
                # Клика на занятую койку достаточно, чтобы уйти в лист
                # наблюдения (vitalschart.html) — id нужен, не только имя.
                "admission_id": active_admission.pk if active_admission else None,
            })
        rooms_by_department = {}
        for room in rooms:
            rooms_by_department.setdefault(room.department_id, []).append(
                {"id": room.pk, "name": room.name, "beds": beds_by_room.get(room.pk, [])}
            )

        data = {
            "occupancy": occupancy,
            "total_beds": len(beds),
            "departments": [
                {
                    "id": department.pk,
                    "name": department.name,
                    "branch": department.branch_id,
                    "branch_name": department.branch.name,
                    "rooms": rooms_by_department.get(department.pk, []),
                }
                for department in departments
            ],
        }
        return Response(data)

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


class ClinicalOrderViewSet(viewsets.ModelViewSet):
    """Назначения — department-scoped, same reach as AdmissionViewSet
    (get_object() resolves ClinicalOrder.department -> admission.
    department for free). Ordering (create/cancel) and execution
    (complete) are deliberately DIFFERENT permission codes — see
    seed_rbac.py: a doctor orders, a nurse executes, and the `complete`
    action overrides required_permission for exactly that reason.
    """

    serializer_class = ClinicalOrderSerializer
    permission_classes = [HasDepartmentPermission]
    required_permission = {
        "GET": "inpatient.order.view",
        "POST": "inpatient.order.manage",
        "PUT": "inpatient.order.manage",
        "PATCH": "inpatient.order.manage",
        "DELETE": "inpatient.order.manage",
    }
    filterset_fields = ["admission", "order_type", "status"]

    def get_queryset(self):
        # required_permission is a per-action string on `complete` (see
        # below — the @action decorator's initkwargs replace it just for
        # that dispatch), a method-keyed dict everywhere else — same
        # dict-or-string shape HasDepartmentPermission._required_code
        # already handles, mirrored here since get_queryset needs the
        # same resolution independently of the permission class.
        required = self.required_permission
        code = required if isinstance(required, str) else required.get(self.request.method, "inpatient.order.view")
        allowed_departments = departments_for_permission(self.request.user, code)
        return ClinicalOrder.objects.filter(admission__department__in=allowed_departments).select_related(
            "admission", "admission__department", "ordered_by", "performed_by"
        )

    def perform_create(self, serializer):
        serializer.save(ordered_by=self.request.user)

    @action(detail=True, methods=["post"], required_permission="inpatient.order.perform")
    def complete(self, request, pk=None):
        """Отмечает назначение выполненным — постовая медсестра
        (inpatient.order.perform), не обязательно тот, кто назначил.
        Повторное выполнение уже выполненного назначения отклоняется —
        тот же паттерн, что LabOrder's result/ guard (Фаза 2)."""
        order = self.get_object()
        if not order.complete(performed_by=request.user, note=request.data.get("performed_note", "")):
            return Response({"detail": "Назначение уже закрыто и не может быть выполнено повторно."}, status=400)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if not order.cancel():
            return Response({"detail": "Назначение уже закрыто и не может быть изменено."}, status=400)
        return Response(self.get_serializer(order).data)


class VitalsRecordViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Лист наблюдения — create/list/retrieve only, no update/destroy at
    all (see VitalsRecord's model docstring: created directly via POST,
    unlike Payment/StockMovement/Transfer whose creation is a side effect
    of another action, but just as immutable afterwards)."""

    serializer_class = VitalsRecordSerializer
    permission_classes = [HasDepartmentPermission]
    required_permission = {
        "GET": "inpatient.vitals.view",
        "POST": "inpatient.vitals.manage",
    }
    filterset_fields = ["admission"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "inpatient.vitals.view")
        allowed_departments = departments_for_permission(self.request.user, code)
        return VitalsRecord.objects.filter(admission__department__in=allowed_departments).select_related(
            "admission", "admission__department", "recorded_by"
        )

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class OperatingRoomViewSet(viewsets.ModelViewSet):
    """Каталог операционных филиала — тот же уровень, что структура
    Room/Bed (см. OperatingRoom's docstring), поэтому HasBranchPermission/
    inpatient.department.* , не отдельный department-scoped код."""

    serializer_class = OperatingRoomSerializer
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
        return OperatingRoom.objects.filter(branch__in=allowed_branches).select_related("branch")


class OperationViewSet(viewsets.ModelViewSet):
    """Операционный модуль — department-scoped через Admission (см.
    Operation.department). Чек-лист безопасности (sign_in/time_out/
    sign_out) — отдельные action'ы под inpatient.operation.checklist:
    хирург/анестезиолог/операционная медсестра могут подтверждать этапы,
    не обязательно тот, кто планировал операцию (inpatient.operation.
    manage) — та же логика разделения "назначил/выполнил", что у
    ClinicalOrder.
    """

    serializer_class = OperationSerializer
    permission_classes = [HasDepartmentPermission]
    required_permission = {
        "GET": "inpatient.operation.view",
        "POST": "inpatient.operation.manage",
        "PUT": "inpatient.operation.manage",
        "PATCH": "inpatient.operation.manage",
        "DELETE": "inpatient.operation.manage",
    }
    filterset_fields = ["admission", "operating_room", "status"]

    def get_queryset(self):
        required = self.required_permission
        code = required if isinstance(required, str) else required.get(self.request.method, "inpatient.operation.view")
        allowed_departments = departments_for_permission(self.request.user, code)
        return Operation.objects.filter(admission__department__in=allowed_departments).select_related(
            "admission", "admission__department", "operating_room", "lead_surgeon",
        ).prefetch_related("team")

    def _checklist_action(self, request, method_name, error_message):
        operation = self.get_object()
        method = getattr(operation, method_name)
        try:
            changed = method(request.user)
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))
        if not changed:
            return Response({"detail": error_message}, status=400)
        return Response(self.get_serializer(operation).data)

    @action(detail=True, methods=["post"], required_permission="inpatient.operation.checklist")
    def sign_in(self, request, pk=None):
        return self._checklist_action(request, "confirm_sign_in", "Sign In уже подтверждён.")

    @action(detail=True, methods=["post"], required_permission="inpatient.operation.checklist")
    def time_out(self, request, pk=None):
        return self._checklist_action(request, "confirm_time_out", "Time Out уже подтверждён.")

    @action(detail=True, methods=["post"], required_permission="inpatient.operation.checklist")
    def sign_out(self, request, pk=None):
        return self._checklist_action(request, "confirm_sign_out", "Sign Out уже подтверждён.")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        operation = self.get_object()
        try:
            changed = operation.complete()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))
        if not changed:
            return Response({"detail": "Операция уже закрыта."}, status=400)
        return Response(self.get_serializer(operation).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        operation = self.get_object()
        if not operation.cancel():
            return Response({"detail": "Операция уже закрыта."}, status=400)
        return Response(self.get_serializer(operation).data)
