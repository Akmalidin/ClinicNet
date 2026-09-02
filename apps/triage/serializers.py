from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.patients.models import Patient

from .models import TriageSuggestion


class TriageSuggestionSerializer(serializers.ModelSerializer):
    specialty_name = serializers.CharField(source="matched_specialty.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    doctor_name = serializers.CharField(source="suggested_doctor.__str__", read_only=True)
    matched_patient_candidate = serializers.SerializerMethodField()

    class Meta:
        model = TriageSuggestion
        fields = (
            "id", "channel", "external_chat_id", "contact_name", "contact_phone", "symptom_text",
            "matched_specialty", "specialty_name", "branch", "branch_name",
            "suggested_doctor", "doctor_name", "suggested_starts_at", "suggested_ends_at",
            "match_confidence",
            "status", "patient", "resulting_appointment",
            "confirmed_by", "confirmed_at", "rejection_reason",
            "matched_patient_candidate",
            "created_at", "updated_at",
        )
        # Создание — только через ingest (triage.ingest, только у
        # сервисного аккаунта бота, см. TriageSuggestionViewSet.create).
        # confirm/reject actions — не сырой PATCH; статус/patient/
        # resulting_appointment/confirmed_* здесь всегда read-only.
        read_only_fields = (
            "id", "status", "patient", "resulting_appointment",
            "confirmed_by", "confirmed_at", "rejection_reason",
            "created_at", "updated_at",
        )

    def get_matched_patient_candidate(self, obj):
        """Удобство для координатора — если телефон из чата совпадает с
        каким-то Patient.phone, подсказываем его в очереди. НЕ
        auto-linking: confirm() всё равно требует явного patient в
        запросе, см. TriageSuggestion.confirm's докстринг."""
        if not obj.contact_phone:
            return None
        candidate = Patient.objects.filter(phone=obj.contact_phone).first()
        if not candidate:
            return None
        return {"id": candidate.pk, "name": str(candidate)}

    def validate(self, attrs):
        if self.instance:
            return attrs
        instance = TriageSuggestion(**attrs)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        return attrs
