from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Referral


class ReferralSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.__str__", read_only=True)
    from_doctor_name = serializers.CharField(source="from_doctor.__str__", read_only=True)
    to_doctor_name = serializers.CharField(
        source="to_doctor.__str__", read_only=True, allow_null=True, default=None
    )
    to_specialty_name = serializers.CharField(
        source="to_specialty.name", read_only=True, allow_null=True, default=None
    )
    from_branch_name = serializers.CharField(source="from_branch.name", read_only=True)
    to_branch_name = serializers.CharField(source="to_branch.name", read_only=True)
    is_cross_branch = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = [
            "id",
            "patient", "patient_name",
            "from_doctor", "from_doctor_name",
            "to_doctor", "to_doctor_name",
            "to_specialty", "to_specialty_name",
            "from_branch", "from_branch_name",
            "to_branch", "to_branch_name",
            "source_visit", "reason", "clinical_note", "diagnosis_snapshot",
            "priority", "status",
            "target_appointment", "outcome_note", "outcome_visible_to",
            "created_at", "updated_at", "scheduled_at", "completed_at",
            "is_cross_branch",
        ]
        # status/target_appointment/scheduled_at/completed_at only change
        # through the schedule/decline/complete actions (views.py), never a
        # raw PATCH — matches ClinicNet-Referrals-Prompt.md section 3.
        # from_doctor is always request.user (see ReferralViewSet.perform_create),
        # never client-supplied — you can't send a referral "from" someone else.
        # diagnosis_snapshot is likewise always derived server-side from
        # source_visit at creation time (perform_create) — the whole point
        # of "snapshot, not live link" (see the model's docstring) is that
        # it can't be handed in and diverge from what the visit actually said.
        read_only_fields = [
            "id", "from_doctor", "status", "target_appointment", "diagnosis_snapshot",
            "created_at", "updated_at", "scheduled_at", "completed_at",
        ]

    def get_is_cross_branch(self, obj):
        return obj.from_branch_id != obj.to_branch_id

    def validate(self, attrs):
        instance = Referral(pk=getattr(self.instance, "pk", None), **{**self._existing_fields(), **attrs})
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        return attrs

    def _existing_fields(self):
        if not self.instance:
            return {}
        return {
            "patient": self.instance.patient,
            "from_doctor": self.instance.from_doctor,
            "to_doctor": self.instance.to_doctor,
            "to_specialty": self.instance.to_specialty,
            "from_branch": self.instance.from_branch,
            "to_branch": self.instance.to_branch,
            "status": self.instance.status,
            "outcome_note": self.instance.outcome_note,
        }
