from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission

from .models import ChurnRisk
from .serializers import ChurnRiskSerializer


class ChurnRiskViewSet(viewsets.ReadOnlyModelViewSet):
    """Алерты оттока, branch-scoped — тот же HasBranchPermission, что
    везде (см. ChurnRisk.branch's докстринг — почему branch, а не
    network-wide, как сам Patient). Read-only + actions: строка
    создаётся только calculate_churn_risks (cron), никогда через POST
    здесь. acknowledge/dismiss/reactivate требуют churn.manage, не
    churn.view — тот же приём, что required_permission-override на
    отдельный action, уже использованный в apps.inpatient (ClinicalOrder.
    complete/Operation's чек-лист): required_permission здесь — обычный
    method-keyed словарь для GET, а на каждый action ниже — своя строка,
    которую HasBranchPermission._required_code уже умеет понимать без
    доработок (dict или строка).
    """

    serializer_class = ChurnRiskSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {"GET": "churn.view"}
    filterset_fields = ["branch", "status"]

    def get_queryset(self):
        required = self.required_permission
        code = required if isinstance(required, str) else required.get(self.request.method, "churn.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return ChurnRisk.objects.filter(branch__in=allowed_branches).select_related("patient", "branch")

    def _transition(self, method_name, error_message):
        risk = self.get_object()
        if not getattr(risk, method_name)():
            return Response({"detail": error_message}, status=400)
        return Response(self.get_serializer(risk).data)

    @action(detail=True, methods=["post"], required_permission="churn.manage")
    def acknowledge(self, request, pk=None):
        return self._transition("acknowledge", "Алерт уже не новый.")

    @action(detail=True, methods=["post"], required_permission="churn.manage")
    def dismiss(self, request, pk=None):
        return self._transition("dismiss", "Алерт уже закрыт.")

    @action(detail=True, methods=["post"], required_permission="churn.manage")
    def reactivate(self, request, pk=None):
        return self._transition("reactivate", "Алерт уже закрыт.")
