from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Admission, Bed, Department, Room, StaffDepartmentAssignment


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
