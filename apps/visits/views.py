from rest_framework import viewsets

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission

from .models import Visit
from .serializers import VisitSerializer


class VisitViewSet(viewsets.ModelViewSet):
    """Visits, scoped to the branches the current user can act in — same
    pattern as AppointmentViewSet. Note this is deliberately DIFFERENT from
    PatientViewSet: the patient CARD is network-wide for anyone with
    patient.view (Phase 2's "единая ЭМК" fix), but a Visit is branch-tied
    clinical activity, so it stays scoped like Appointment. A user with
    branch access to both of a patient's branches (e.g. an all-scope
    network admin) sees the patient's full visit history across both; a
    single-branch doctor sees only the visits in their own branch(es) —
    that's RBAC working as intended, not the "карта = один филиал" bug.
    """

    serializer_class = VisitSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "visit.view",
        "POST": "visit.manage",
        "PUT": "visit.manage",
        "PATCH": "visit.manage",
        "DELETE": "visit.manage",
    }
    filterset_fields = ["branch", "doctor", "patient", "status"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "visit.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return (
            Visit.objects.filter(branch__in=allowed_branches)
            .select_related("branch", "patient", "doctor", "appointment")
        )
