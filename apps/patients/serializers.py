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
            "created_at",
        )
        read_only_fields = ("id", "created_at")
