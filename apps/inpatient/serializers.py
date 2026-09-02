from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    Admission,
    Bed,
    ClinicalOrder,
    Department,
    Operation,
    OperatingRoom,
    Room,
    StaffDepartmentAssignment,
    Transfer,
    VitalsRecord,
)


class DepartmentSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Department
        fields = ("id", "branch", "branch_name", "name", "code", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class RoomSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Room
        fields = ("id", "department", "department_name", "name", "is_active")
        read_only_fields = ("id",)


class BedSerializer(serializers.ModelSerializer):
    room_name = serializers.CharField(source="room.name", read_only=True)
    department_id = serializers.IntegerField(source="department.id", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Bed
        fields = (
            "id", "room", "room_name", "department_id", "department_name",
            "label", "status", "created_at",
        )
        # status is intentionally read-only here — it changes only via
        # BedViewSet.set_status (FREE/CLEANING/RESERVED) or as a side
        # effect of admission/discharge (OCCUPIED), never a raw PATCH.
        # See Bed's model docstring.
        read_only_fields = ("id", "status", "created_at")


class StaffDepartmentAssignmentSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.__str__", read_only=True)
    department_name = serializers.CharField(source="department.__str__", read_only=True)

    class Meta:
        model = StaffDepartmentAssignment
        fields = ("id", "staff", "staff_name", "department", "department_name", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class AdmissionSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.__str__", read_only=True)
    department_name = serializers.CharField(source="department.__str__", read_only=True)
    bed_label = serializers.CharField(source="bed.label", read_only=True)
    room_name = serializers.CharField(source="bed.room.name", read_only=True)
    attending_doctor_name = serializers.CharField(source="attending_doctor.__str__", read_only=True)
    admitted_by_name = serializers.CharField(source="admitted_by.__str__", read_only=True)

    class Meta:
        model = Admission
        fields = (
            "id",
            "patient", "patient_name",
            "department", "department_name",
            "bed", "bed_label", "room_name",
            "attending_doctor", "attending_doctor_name",
            "admitted_by", "admitted_by_name",
            "diagnosis_at_admission", "status",
            "admitted_at", "discharged_at", "discharge_epicrisis",
            "updated_at",
        )
        # Creation goes through AdmissionViewSet.create() ->
        # apps.inpatient.services.admit_patient (occupies the bed
        # atomically) — admitted_by/status/admitted_at/discharged_at
        # aren't client-writable. Discharge is the `discharge` action,
        # not a raw PATCH — same reasoning as Invoice/Referral/LabOrder's
        # terminal-state transitions.
        read_only_fields = (
            "id", "patient", "department", "bed", "admitted_by", "status",
            "admitted_at", "discharged_at", "discharge_epicrisis", "updated_at",
        )
        # patient/department/bed are read-only even on update — reassigning
        # the patient makes no sense on an existing admission, and
        # department/bed changes go through a dedicated transfer flow
        # (Фаза 4 шаг c, not built yet), which needs to log Transfer
        # history and re-run the bed-clash/occupancy side effects — a raw
        # PATCH here would silently skip both.

    def validate(self, attrs):
        # Only relevant on update (attending_doctor/diagnosis_at_admission
        # edits while active) — creation bypasses the serializer entirely
        # (see AdmissionViewSet.create). Runs Admission.clean() so the
        # terminal-status guard applies here too.
        if not self.instance:
            return attrs
        instance = Admission(
            pk=self.instance.pk,
            patient=self.instance.patient,
            department=self.instance.department,
            bed=self.instance.bed,
            attending_doctor=attrs.get("attending_doctor", self.instance.attending_doctor),
            admitted_by=self.instance.admitted_by,
            diagnosis_at_admission=attrs.get("diagnosis_at_admission", self.instance.diagnosis_at_admission),
            status=self.instance.status,
        )
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        return attrs


class TransferSerializer(serializers.ModelSerializer):
    from_department_name = serializers.CharField(source="from_department.name", read_only=True)
    to_department_name = serializers.CharField(source="to_department.name", read_only=True)
    from_bed_label = serializers.CharField(source="from_bed.label", read_only=True)
    to_bed_label = serializers.CharField(source="to_bed.label", read_only=True)
    transferred_by_name = serializers.CharField(source="transferred_by.__str__", read_only=True)

    class Meta:
        model = Transfer
        fields = (
            "id", "admission",
            "from_department", "from_department_name", "from_bed", "from_bed_label",
            "to_department", "to_department_name", "to_bed", "to_bed_label",
            "reason", "transferred_by", "transferred_by_name", "transferred_at",
        )
        # Append-only ledger — created only by AdmissionViewSet.transfer
        # (apps.inpatient.services.transfer_admission), same shape as
        # apps.finance.PaymentSerializer/apps.inventory.
        # StockMovementSerializer.
        read_only_fields = fields


class ClinicalOrderSerializer(serializers.ModelSerializer):
    ordered_by_name = serializers.CharField(source="ordered_by.__str__", read_only=True)
    performed_by_name = serializers.CharField(source="performed_by.__str__", read_only=True, default=None)

    class Meta:
        model = ClinicalOrder
        fields = (
            "id", "admission", "order_type", "description", "scheduled_for",
            "ordered_by", "ordered_by_name", "status",
            "performed_by", "performed_by_name", "performed_at", "performed_note",
            "created_at", "updated_at",
        )
        # Execution (performed_*) happens only through the `complete`
        # action, cancellation through `cancel` — same terminal-status
        # transition shape as Invoice/Referral/LabOrder, never a raw
        # PATCH on status.
        read_only_fields = (
            "id", "ordered_by", "status", "performed_by", "performed_at",
            "performed_note", "created_at", "updated_at",
        )

    def validate(self, attrs):
        if self.instance:
            # Editing an existing order (description/scheduled_for while
            # still ORDERED) — re-run clean() so the terminal-status
            # guard applies here too.
            instance = ClinicalOrder(
                pk=self.instance.pk,
                admission=self.instance.admission,
                order_type=attrs.get("order_type", self.instance.order_type),
                description=attrs.get("description", self.instance.description),
                scheduled_for=attrs.get("scheduled_for", self.instance.scheduled_for),
                ordered_by=self.instance.ordered_by,
                status=self.instance.status,
            )
        else:
            instance = ClinicalOrder(
                admission=attrs.get("admission"),
                order_type=attrs.get("order_type"),
                description=attrs.get("description"),
                scheduled_for=attrs.get("scheduled_for"),
            )
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        return attrs


class VitalsRecordSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source="recorded_by.__str__", read_only=True)

    class Meta:
        model = VitalsRecord
        fields = (
            "id", "admission", "recorded_by", "recorded_by_name",
            "blood_pressure_systolic", "blood_pressure_diastolic", "pulse", "temperature",
            "note", "recorded_at",
        )
        # Append-only — VitalsRecordViewSet has no update/destroy at all
        # (see the model's docstring), so recorded_by/recorded_at are the
        # only genuinely server-set fields; nothing here is ever PATCHed.
        read_only_fields = ("id", "recorded_by", "recorded_at")

    def validate(self, attrs):
        instance = VitalsRecord(
            admission=attrs.get("admission"),
            blood_pressure_systolic=attrs.get("blood_pressure_systolic"),
            blood_pressure_diastolic=attrs.get("blood_pressure_diastolic"),
            pulse=attrs.get("pulse"),
            temperature=attrs.get("temperature"),
        )
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        return attrs


class OperatingRoomSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = OperatingRoom
        fields = ("id", "branch", "branch_name", "name", "is_active")
        read_only_fields = ("id",)


class OperationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="admission.patient.__str__", read_only=True)
    operating_room_name = serializers.CharField(source="operating_room.name", read_only=True)
    lead_surgeon_name = serializers.CharField(source="lead_surgeon.__str__", read_only=True)
    branch_name = serializers.CharField(source="admission.department.branch.name", read_only=True)
    team_detail = serializers.SerializerMethodField()

    class Meta:
        model = Operation
        fields = (
            "id", "admission", "patient_name", "operating_room", "operating_room_name",
            "branch_name",
            "procedure_name", "starts_at", "ends_at", "lead_surgeon", "lead_surgeon_name", "team",
            "team_detail",
            "status",
            "sign_in_confirmed_by", "sign_in_confirmed_at",
            "time_out_confirmed_by", "time_out_confirmed_at",
            "sign_out_confirmed_by", "sign_out_confirmed_at",
            "created_at", "updated_at",
        )
        # Чек-лист (sign_in/time_out/sign_out) выставляется только через
        # confirm_sign_in/confirm_time_out/confirm_sign_out actions —
        # никогда сырым PATCH, тот же принцип, что статус у Invoice/
        # Referral/LabOrder/Admission. status меняется только через
        # complete/cancel actions.
        read_only_fields = (
            "id", "status",
            "sign_in_confirmed_by", "sign_in_confirmed_at",
            "time_out_confirmed_by", "time_out_confirmed_at",
            "sign_out_confirmed_by", "sign_out_confirmed_at",
            "created_at", "updated_at",
        )

    def validate(self, attrs):
        existing = {
            "admission": self.instance.admission, "operating_room": self.instance.operating_room,
            "procedure_name": self.instance.procedure_name, "starts_at": self.instance.starts_at,
            "ends_at": self.instance.ends_at, "lead_surgeon": self.instance.lead_surgeon,
            "status": self.instance.status,
        } if self.instance else {}
        instance = Operation(pk=getattr(self.instance, "pk", None), **{**existing, **{
            k: v for k, v in attrs.items() if k != "team"
        }})
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        return attrs

    def get_team_detail(self, obj):
        # Свободный job_title (apps.accounts.User), не роль-в-операции —
        # такого поля в модели нет (team — плоский M2M, см. Operation's
        # докстринг), не выдумываем то, чего нет в данных.
        return [
            {"id": member.pk, "name": str(member), "job_title": member.job_title}
            for member in obj.team.all()
        ]
