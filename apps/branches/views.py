from rest_framework import viewsets

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission

from .models import Branch, StaffBranchAssignment
from .serializers import BranchSerializer, StaffBranchAssignmentSerializer


class BranchViewSet(viewsets.ModelViewSet):
    """Branches, filtered to what the current user is allowed to see.

    A user only sees branches covered by an active grant of
    "branch.view" — network admins (branch_scope=all) see everything,
    others see only their own/assigned branches. This is what lets the
    schedule UI filter by branch without a manual context switch.
    """

    serializer_class = BranchSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "branch.view",
        "POST": "branch.manage",
        "PUT": "branch.manage",
        "PATCH": "branch.manage",
        "DELETE": "branch.manage",
    }

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "branch.view")
        return branches_for_permission(self.request.user, code)


class StaffBranchAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = StaffBranchAssignmentSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "branch.schedule.view",
        "POST": "branch.schedule.manage",
        "PUT": "branch.schedule.manage",
        "PATCH": "branch.schedule.manage",
        "DELETE": "branch.schedule.manage",
    }
    filterset_fields = ["branch", "staff", "weekday", "is_active"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "branch.schedule.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return StaffBranchAssignment.objects.filter(branch__in=allowed_branches).select_related(
            "staff", "branch"
        )
