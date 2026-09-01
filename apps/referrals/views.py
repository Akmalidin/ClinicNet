from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.rbac import branches_for_permission
from apps.branches.models import StaffBranchAssignment
from apps.scheduling.models import ACTIVE_STATUSES, Appointment

from .models import Referral, ReferralStatus
from .permissions import HasReferralPermission
from .serializers import ReferralSerializer
from .services import notify_referral_created, notify_referral_declined, notify_referral_completed

SLOT_MINUTES = 30


class ReferralViewSet(viewsets.ModelViewSet):
    serializer_class = ReferralSerializer
    permission_classes = [HasReferralPermission]
    # No code for list/create/available_slots — HasReferralPermission only
    # requires authentication there (see its docstring: "own" is an
    # unconditional baseline, referrals.view/manage are the coordinator/
    # network escalation, applied via get_queryset below and via
    # has_object_permission for the other actions).
    required_permission = {
        "retrieve": "referrals.view",
        "update": "referrals.manage",
        "partial_update": "referrals.manage",
        "destroy": "referrals.manage",
        "schedule": "referrals.manage",
        "decline": "referrals.manage",
        "complete": "referrals.manage",
    }
    filterset_fields = ["status", "priority", "to_doctor", "from_doctor"]

    def get_queryset(self):
        user = self.request.user
        qs = Referral.objects.select_related(
            "patient", "from_doctor", "to_doctor", "to_specialty",
            "from_branch", "to_branch", "source_visit", "target_appointment",
        )
        if not user.is_authenticated:
            return qs.none()

        # "Видит своё" — базовое право любого врача, независимо от branch_scope.
        own = Q(from_doctor=user) | Q(to_doctor=user)

        code = self.required_permission.get(self.action, "referrals.view")
        allowed_branches = branches_for_permission(user, code)
        branch_scoped = Q(from_branch__in=allowed_branches) | Q(to_branch__in=allowed_branches)

        qs = qs.filter(own | branch_scoped).distinct()

        branch_id = self.request.query_params.get("branch")
        if branch_id:
            qs = qs.filter(Q(from_branch_id=branch_id) | Q(to_branch_id=branch_id))
        if self.request.query_params.get("cross_branch_only"):
            qs = qs.exclude(from_branch_id=F("to_branch_id"))
        return qs

    def perform_create(self, serializer):
        # diagnosis_snapshot is meant to be a snapshot of the source visit
        # AT THE MOMENT OF REFERRAL (see Referral docstring / the model's
        # own comment) — captured server-side from source_visit, same as
        # from_doctor, rather than trusted from the client (see
        # ReferralSerializer.read_only_fields).
        source_visit = serializer.validated_data.get("source_visit")
        snapshot = source_visit.diagnosis_snapshot if source_visit else {}
        referral = serializer.save(from_doctor=self.request.user, diagnosis_snapshot=snapshot)
        notify_referral_created(referral)

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        """Подтвердить слот у принимающего врача — привязать target_appointment."""
        referral = self.get_object()
        appointment_id = request.data.get("target_appointment")
        if not appointment_id:
            return Response({"target_appointment": "Обязательное поле."}, status=400)
        appointment = get_object_or_404(Appointment, pk=appointment_id)

        errors = {}
        if referral.to_doctor_id and appointment.doctor_id != referral.to_doctor_id:
            errors["target_appointment"] = "Запись должна быть у принимающего врача направления."
        if appointment.branch_id != referral.to_branch_id:
            errors.setdefault(
                "target_appointment", "Запись должна быть в филиале назначения направления."
            )
        if errors:
            return Response(errors, status=400)

        referral.target_appointment = appointment
        if not referral.to_doctor_id:
            # Направление было "на специальность" — теперь врач найден по записи.
            referral.to_doctor = appointment.doctor
        referral.status = ReferralStatus.SCHEDULED
        referral.scheduled_at = timezone.now()
        try:
            referral.full_clean()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        referral.save()
        return Response(self.get_serializer(referral).data)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        """Требует outcome_note с причиной отказа."""
        referral = self.get_object()
        outcome_note = (request.data.get("outcome_note") or "").strip()
        if not outcome_note:
            return Response(
                {"outcome_note": "При отклонении направления причина обязательна."}, status=400
            )
        referral.status = ReferralStatus.DECLINED
        referral.outcome_note = outcome_note
        try:
            referral.full_clean()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        referral.save()
        notify_referral_declined(referral)
        return Response(self.get_serializer(referral).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Закрыть направление вручную (обычно это делает сигнал на
        Appointment.status -> completed, см. apps/referrals/signals.py —
        это ручной путь для завершения без привязанной записи)."""
        referral = self.get_object()
        if not referral.mark_completed(request.data.get("outcome_note", "")):
            return Response(
                {"detail": "Направление уже закрыто и не может быть изменено."}, status=400
            )
        notify_referral_completed(referral)
        return Response(self.get_serializer(referral).data)

    @action(detail=False, methods=["get"])
    def available_slots(self, request):
        """Свободные окна врача на дату — считаем сами (в проекте нет
        готового источника "свободных слотов" для проксирования): смены
        StaffBranchAssignment на день недели этой даты, минус занятые
        активные Appointment в этот день, минус уже прошедшее время,
        если date — сегодня.

        Уже прошедшее время исключается явно (found live while building
        Фаза 5's triage_service — apps.triage's find_nearest_slot ловил
        сегодняшние окна, которые фактически уже наступили и прошли,
        потому что эта проверка изначально жила только в клиенте
        triage_service, а не здесь; у любого вызывающего этого эндпоинта
        нет причины хотеть прошедшее время как "свободное", так что фикс
        — здесь, в первоисточнике, а не в одном из потребителей)."""
        doctor_id = request.query_params.get("doctor")
        date_str = request.query_params.get("date")
        if not doctor_id or not date_str:
            return Response({"detail": "Укажите doctor и date."}, status=400)
        doctor = get_object_or_404(User, pk=doctor_id)
        date = parse_date(date_str)
        if date is None:
            return Response({"detail": "date должен быть в формате YYYY-MM-DD."}, status=400)

        shifts = StaffBranchAssignment.objects.filter(
            staff=doctor, weekday=date.weekday(), is_active=True
        ).select_related("branch")
        busy = list(
            Appointment.objects.filter(
                doctor=doctor, status__in=ACTIVE_STATUSES, starts_at__date=date
            ).values_list("starts_at", "ends_at")
        )
        now = timezone.now()

        slots = []
        for shift in shifts:
            tz = ZoneInfo(shift.branch.timezone)
            cursor = datetime.combine(date, shift.start_time, tzinfo=tz)
            shift_end = datetime.combine(date, shift.end_time, tzinfo=tz)
            while cursor + timedelta(minutes=SLOT_MINUTES) <= shift_end:
                slot_end = cursor + timedelta(minutes=SLOT_MINUTES)
                if cursor > now and not any(b_start < slot_end and b_end > cursor for b_start, b_end in busy):
                    slots.append(
                        {
                            "branch": shift.branch_id,
                            "branch_name": shift.branch.name,
                            "starts_at": cursor.isoformat(),
                            "ends_at": slot_end.isoformat(),
                        }
                    )
                cursor = slot_end
        return Response(slots)
