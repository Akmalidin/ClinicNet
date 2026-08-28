from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Appointment


class AppointmentSerializer(serializers.ModelSerializer):
    patient_display = serializers.CharField(source="patient.__str__", read_only=True)
    doctor_display = serializers.CharField(source="doctor.__str__", read_only=True)
    branch_display = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Appointment
        fields = (
            "id",
            "branch",
            "branch_display",
            "patient",
            "patient_display",
            "doctor",
            "doctor_display",
            "starts_at",
            "ends_at",
            "status",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        instance = Appointment(pk=getattr(self.instance, "pk", None), **{**self._existing_fields(), **attrs})
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
        return attrs

    def _existing_fields(self):
        if not self.instance:
            return {}
        return {
            "branch": self.instance.branch,
            "patient": self.instance.patient,
            "doctor": self.instance.doctor,
            "starts_at": self.instance.starts_at,
            "ends_at": self.instance.ends_at,
            "status": self.instance.status,
        }
