from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, serializers as drf_serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
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
        """patient — обязателен. doctor/starts_at/ends_at — необязательное
        "Изменить слот": координатор подтверждает на другого врача/время
        того же филиала вместо предложенного ботом, см.
        TriageSuggestion.confirm's докстринг. Передавать нужно либо все
        три вместе, либо ни одного — частичная замена (например, только
        время без врача) не имеет однозначного смысла."""
        suggestion = self.get_object()
        patient_id = request.data.get("patient")
        if not patient_id:
            return Response({"detail": "Укажите patient — существующего пациента."}, status=400)
        try:
            patient = Patient.objects.get(pk=patient_id)
        except (Patient.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Пациент не найден."}, status=400)

        overrides = {}
        raw_doctor = request.data.get("doctor")
        raw_starts = request.data.get("starts_at")
        raw_ends = request.data.get("ends_at")
        if raw_doctor or raw_starts or raw_ends:
            if not (raw_doctor and raw_starts and raw_ends):
                return Response(
                    {"detail": "Для замены слота укажите doctor, starts_at и ends_at вместе."}, status=400
                )
            try:
                overrides["doctor"] = User.objects.get(pk=raw_doctor)
            except (User.DoesNotExist, ValueError, TypeError):
                return Response({"detail": "Врач не найден."}, status=400)
            overrides["starts_at"] = parse_datetime(str(raw_starts))
            overrides["ends_at"] = parse_datetime(str(raw_ends))
            if not overrides["starts_at"] or not overrides["ends_at"]:
                return Response({"detail": "starts_at/ends_at должны быть в формате ISO 8601."}, status=400)

        try:
            changed = suggestion.confirm(confirmed_by=request.user, patient=patient, **overrides)
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))

        if not changed:
            if overrides:
                detail = "Указанное время уже прошло — выберите другой слот."
            elif suggestion.status == "expired":
                detail = "Предложенный слот уже прошёл — предложение помечено как истёкшее."
            else:
                detail = "Предложение уже закрыто."
            return Response({"detail": detail}, status=400)
        return Response(self.get_serializer(suggestion).data)

    @action(detail=True, methods=["post"], required_permission="triage.manage")
    def reject(self, request, pk=None):
        suggestion = self.get_object()
        if not suggestion.reject(reason=request.data.get("reason", "")):
            return Response({"detail": "Предложение уже закрыто."}, status=400)
        return Response(self.get_serializer(suggestion).data)
