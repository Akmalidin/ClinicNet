from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, serializers as drf_serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission
from apps.patients.models import Patient

from .models import TriageSuggestion
from .serializers import TriageSuggestionSerializer


def _validation_detail(exc: DjangoValidationError):
    return exc.message_dict if hasattr(exc, "message_dict") else exc.messages


class TriageSuggestionViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Очередь предложений AI-триажа. create — только сервисный аккаунт
    бота (triage.ingest, обычно ALL-scope — бот не привязан к одному
    филиалу, предлагает слот там, где ближе); GET/confirm/reject —
    координатор с triage.view/triage.manage на конкретном филиале, тот
    же HasBranchPermission, что везде (branch резолвится из поля
    `branch`, см. модель). Никакого update/destroy — предложение либо
    подтверждается, либо отклоняется, действиями, не сырым PATCH.
    """

    serializer_class = TriageSuggestionSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {"GET": "triage.view", "POST": "triage.ingest"}
    filterset_fields = ["branch", "status", "channel"]

    def get_queryset(self):
        required = self.required_permission
        code = required if isinstance(required, str) else required.get(self.request.method, "triage.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return TriageSuggestion.objects.filter(branch__in=allowed_branches).select_related(
            "matched_specialty", "branch", "suggested_doctor", "patient", "confirmed_by",
        )

    @action(detail=True, methods=["post"], required_permission="triage.manage")
    def confirm(self, request, pk=None):
        suggestion = self.get_object()
        patient_id = request.data.get("patient")
        if not patient_id:
            return Response({"detail": "Укажите patient — существующего пациента."}, status=400)
        try:
            patient = Patient.objects.get(pk=patient_id)
        except (Patient.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Пациент не найден."}, status=400)

        try:
            changed = suggestion.confirm(confirmed_by=request.user, patient=patient)
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))

        if not changed:
            detail = (
                "Предложенный слот уже прошёл — предложение помечено как истёкшее."
                if suggestion.status == "expired"
                else "Предложение уже закрыто."
            )
            return Response({"detail": detail}, status=400)
        return Response(self.get_serializer(suggestion).data)

    @action(detail=True, methods=["post"], required_permission="triage.manage")
    def reject(self, request, pk=None):
        suggestion = self.get_object()
        if not suggestion.reject(reason=request.data.get("reason", "")):
            return Response({"detail": "Предложение уже закрыто."}, status=400)
        return Response(self.get_serializer(suggestion).data)
