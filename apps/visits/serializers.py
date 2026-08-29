from rest_framework import serializers

from .models import Visit


class VisitSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.__str__", read_only=True)
    doctor_name = serializers.CharField(source="doctor.__str__", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Visit
        fields = (
            "id", "patient", "patient_name", "doctor", "doctor_name",
            "branch", "branch_name", "appointment",
            "reason", "clinical_note", "diagnosis_snapshot",
            "status", "created_at", "updated_at", "closed_at",
        )
        # status is writable directly (unlike Referral.status) — Visit has
        # no clean()-enforced transition rules requiring a dedicated action.
        read_only_fields = ("id", "created_at", "updated_at", "closed_at")
