from datetime import datetime

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission
from apps.branches.models import StaffBranchAssignment

from .models import Appointment, AppointmentStatus
from .serializers import AppointmentSerializer

# "Занято" для загрузки врачей — приёмы, которые РЕАЛЬНО заняли время
# врача (в т.ч. уже прошедшие COMPLETED), а не только ещё-не-закрытые
# ACTIVE_STATUSES (тот кортеж — для guard'а двойного бронирования, не
# для этого расчёта; отменённые/неявка время не заняли).
OCCUPYING_STATUSES = (
    AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS, AppointmentStatus.COMPLETED,
)


class AppointmentViewSet(viewsets.ModelViewSet):
    """Appointments, scoped to the branches the current user can act in.

    This is the API-level counterpart of "расписание фильтруется по
    филиалу без ручного переключения контекста": the client never has to
    pick a branch to get a correctly-scoped list.
    """

    serializer_class = AppointmentSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "appointment.view",
        "POST": "appointment.manage",
        "PUT": "appointment.manage",
        "PATCH": "appointment.manage",
        "DELETE": "appointment.manage",
    }
    filterset_fields = ["branch", "doctor", "patient", "status"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "appointment.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        qs = (
            Appointment.objects.filter(branch__in=allowed_branches)
            .select_related("branch", "patient", "doctor", "referral", "referral__from_doctor")
        )
        # ?date=YYYY-MM-DD — найдено при разведке multibranchschedule.html:
        # расписание по СЕТИ на один день не вытянуть иначе (filterset_
        # fields — только exact-match, starts_at там нет и точное
        # совпадение с datetime всё равно бесполезно).
        date_param = self.request.query_params.get("date")
        if date_param:
            parsed = parse_date(date_param)
            if parsed:
                qs = qs.filter(starts_at__date=parsed)
        # ?date_from=/?date_to=YYYY-MM-DD — найдено при разведке
        # networkanalytics.html: "воронка приёма" за 30 дней сетью не
        # вытянуть однодневным ?date= выше, а тянуть всё и резать на
        # клиенте не хотелось (тот же принцип, что уже привёл к ?date=
        # и AppointmentViewSet.utilization — фильтрация на бэкенде, не
        # на клиенте). Тот же naming convention, что FinanceReportView.
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            parsed = parse_date(date_from)
            if parsed:
                qs = qs.filter(starts_at__date__gte=parsed)
        if date_to:
            parsed = parse_date(date_to)
            if parsed:
                qs = qs.filter(starts_at__date__lte=parsed)
        return qs

    @action(detail=False, methods=["get"], required_permission="appointment.view")
    def utilization(self, request):
        """Загрузка врачей за день — доля забронированного времени от
        доступного, найдено при разведке networkdashboard.html: KPI
        "загрузка врачей" нигде не считался. "Доступно" — те же смены
        StaffBranchAssignment, что apps.referrals.available_slots уже
        использует для поиска слота (тот же источник правды о рабочих
        часах, не выдуманный отдельно); "занято" — реальные Appointment
        этого дня, которые фактически заняли время врача (включая уже
        прошедшие COMPLETED, но не отменённые/неявку — см.
        OCCUPYING_STATUSES выше).
        """
        allowed_branches = branches_for_permission(request.user, "appointment.view")
        date_param = request.query_params.get("date")
        target_date = parse_date(date_param) if date_param else timezone.localdate()
        if target_date is None:
            return Response({"detail": "date должен быть в формате ISO 8601 (YYYY-MM-DD)."}, status=400)

        assignments = StaffBranchAssignment.objects.filter(
            branch__in=allowed_branches, weekday=target_date.weekday(),
        )
        available_minutes = sum(
            (
                datetime.combine(target_date, a.end_time) - datetime.combine(target_date, a.start_time)
            ).total_seconds() / 60
            for a in assignments
        )

        appointments = Appointment.objects.filter(
            branch__in=allowed_branches, starts_at__date=target_date, status__in=OCCUPYING_STATUSES,
        )
        booked_minutes = sum((a.ends_at - a.starts_at).total_seconds() / 60 for a in appointments)

        utilization_percent = round(booked_minutes / available_minutes * 100, 1) if available_minutes else None
        return Response({
            "date": target_date.isoformat(),
            "available_minutes": round(available_minutes),
            "booked_minutes": round(booked_minutes),
            "utilization_percent": utilization_percent,
        })
