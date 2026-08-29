from rest_framework import serializers

from .models import Branch, StaffBranchAssignment


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ("id", "name", "code", "address", "timezone", "status", "phone", "created_at")
        read_only_fields = ("id", "created_at")


class BranchDirectorySerializer(serializers.ModelSerializer):
    """Deliberately minimal — no address/phone/timezone — see
    BranchDirectoryView's docstring for why this exists at all."""

    class Meta:
        model = Branch
        fields = ("id", "name", "code")


class StaffBranchAssignmentSerializer(serializers.ModelSerializer):
    staff_display = serializers.CharField(source="staff.__str__", read_only=True)
    branch_display = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = StaffBranchAssignment
        fields = (
            "id",
            "staff",
            "staff_display",
            "branch",
            "branch_display",
            "weekday",
            "start_time",
            "end_time",
            "is_active",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        start_time = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end_time = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError("Время начала смены должно быть раньше времени окончания.")
        return attrs
