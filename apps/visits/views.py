from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission
from apps.inventory.services import consume_for_visit

from .models import Visit, VisitStatus
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

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Closes the visit (IN_PROGRESS -> COMPLETED) and, if
        `consumed_items` ([{"product": id, "quantity": ...}, ...]) is
        given, records the matching stock consumption in the same action
        — see apps.inventory.services.consume_for_visit for the
        all-or-nothing validation (Phase 3 step (d): "списание расходника
        при закрытии Visit").

        This is also what finally gives Visit.closed_at a real code path:
        before this action existed, the only way to "close" a visit
        through the API was a raw PATCH on `status` (status is a plain
        writable field on VisitSerializer, with no state-transition
        guard), which never called Visit.close() at all — found during
        Phase 3 recon, not incidentally while building this.

        Consumption is validated and recorded BEFORE close() runs, but
        only after confirming the visit is actually still IN_PROGRESS —
        otherwise a retried request against an already-closed visit could
        record stock consumption for a close() call that then turns out
        to be a no-op.
        """
        visit = self.get_object()
        if visit.status != VisitStatus.IN_PROGRESS:
            return Response({"detail": "Приём уже закрыт или отменён."}, status=400)

        items = request.data.get("consumed_items") or []
        try:
            consume_for_visit(visit, items, request.user)
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )

        visit.close()  # guaranteed True — status was just confirmed IN_PROGRESS above
        return Response(self.get_serializer(visit).data)
