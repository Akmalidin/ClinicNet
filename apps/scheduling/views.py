from rest_framework import viewsets

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
        return (
            Appointment.objects.filter(branch__in=allowed_branches)
            .select_related("branch", "patient", "doctor", "referral", "referral__from_doctor")
        )
