from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Appointment


class AppointmentSerializer(serializers.ModelSerializer):
    patient_display = serializers.CharField(source="patient.__str__", read_only=True)
    doctor_display = serializers.CharField(source="doctor.__str__", read_only=True)
    branch_display = serializers.CharField(source="branch.name", read_only=True)
    referral = serializers.SerializerMethodField()

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
            "referral",
        )
        read_only_fields = ("id", "created_at", "updated_at", "referral")

    def get_referral(self, obj):
        """Null unless this appointment was created from a Referral (its
        target_appointment, see apps.referrals.models) — feeds
        ReferralBadge.vue's icon + tooltip (reason + who referred). Not a
        model import (apps.referrals.Referral) — the reverse o2o accessor
        (related_name="referral") is enough, and it keeps this app from
        having to import apps.referrals at all, one-way dependency only.
        """
        try:
            referral = obj.referral
        except ObjectDoesNotExist:
            return None
        return {
            "id": referral.id,
            "reason": referral.reason,
            "priority": referral.priority,
            "from_doctor_name": str(referral.from_doctor),
        }

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
