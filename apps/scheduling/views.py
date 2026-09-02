from rest_framework import viewsets

from django.utils.dateparse import parse_date

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission

from .models import Appointment
from .serializers import AppointmentSerializer


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
        # совпадение с datetime всё равно бесполезно). Единственный
        # календарный фильтр, который сейчас реально нужен клиенту, —
        # день целиком; диапазон/gte-lte не добавляем, пока нет
        # экрана, которому он нужен.
        date_param = self.request.query_params.get("date")
        if date_param:
            parsed = parse_date(date_param)
            if parsed:
                qs = qs.filter(starts_at__date=parsed)
        return qs
