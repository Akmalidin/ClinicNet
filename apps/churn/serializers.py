from rest_framework import serializers

from .models import ChurnRisk


class ChurnRiskSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.__str__", read_only=True)
    patient_phone = serializers.CharField(source="patient.phone", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = ChurnRisk
        fields = (
            "id", "patient", "patient_name", "patient_phone",
            "branch", "branch_name",
            "last_visit_date", "avg_interval_days", "days_overdue", "risk_score",
            "status", "created_at", "updated_at",
        )
        # Создаётся и пересчитывается только apps.churn.services.
        # calculate_churn_risks (через cron) — вся модель read-only здесь,
        # статус меняется только через acknowledge/dismiss/reactivate
        # actions, тот же принцип, что Invoice/Referral/LabOrder/Admission.
        read_only_fields = fields
