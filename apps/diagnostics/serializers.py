from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import LabOrder, LabResult


class LabResultSerializer(serializers.ModelSerializer):
    entered_by_name = serializers.CharField(source="entered_by.__str__", read_only=True)

    class Meta:
        model = LabResult
        fields = ("id", "order", "entered_by", "entered_by_name", "result_text", "is_abnormal", "entered_at")
        # entered_by is always request.user (see LabOrderViewSet.result),
        # same treatment as Referral.from_doctor — never client-supplied.
        read_only_fields = ("id", "order", "entered_by", "entered_at")


class LabOrderSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.__str__", read_only=True)
    ordered_by_name = serializers.CharField(source="ordered_by.__str__", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    result = serializers.SerializerMethodField()

    class Meta:
        model = LabOrder
        fields = (
            "id",
            "patient", "patient_name",
            "ordered_by", "ordered_by_name",
            "branch", "branch_name",
            "source_visit",
            "test_type", "comment", "urgency",
            "status",
            "created_at", "updated_at",
            "result",
        )
        # status only changes through the result/cancel actions (views.py),
        # never a raw PATCH — same reasoning as Referral.status.
        read_only_fields = ("id", "ordered_by", "status", "created_at", "updated_at", "result")

    def get_result(self, obj):
        try:
            result = obj.result
        except ObjectDoesNotExist:
            return None
        return LabResultSerializer(result).data

    def validate(self, attrs):
        instance = LabOrder(pk=getattr(self.instance, "pk", None), **{**self._existing_fields(), **attrs})
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
            "ordered_by": self.instance.ordered_by,
            "branch": self.instance.branch,
            "status": self.instance.status,
        }
