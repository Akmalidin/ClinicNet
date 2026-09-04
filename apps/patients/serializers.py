from rest_framework import serializers

from .models import Patient


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = (
            "id",
            "first_name",
            "last_name",
            "phone",
            "email",
            "date_of_birth",
            "primary_branch",
            "notes",
            "loyalty_points",
            "created_at",
        )
        # loyalty_points — списывается только InvoiceViewSet.pay() (метод
        # bonus), правится вручную через admin; нет API-пути начислить их
        # через обычный PATCH /patients/, тот же принцип "один
        # контролируемый путь записи", что у InsurancePolicy.used_amount.
        read_only_fields = ("id", "loyalty_points", "created_at")
