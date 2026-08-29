from rest_framework import generics, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission

from .models import Branch, BranchStatus, StaffBranchAssignment
from .serializers import BranchDirectorySerializer, BranchSerializer, StaffBranchAssignmentSerializer


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


class BranchDirectoryView(generics.ListAPIView):
    """Every active branch in the network, id/name/code only.

    Deliberately NOT scoped by branch.view like BranchViewSet above: that
    permission answers "which branches can this user administratively see
    /manage", and a plain doctor with own_branch scope only ever gets their
    own branch there — which breaks the cross-branch referral picker
    (specialty -> BRANCH -> doctor, ClinicNet-Referrals-Prompt.md section
    6), since routing a referral to another branch requires knowing that
    branch exists at all, independent of any administrative grant on it.
    Same shape as the "own" bypass in referrals — a read-only network
    directory is a baseline for any authenticated staff member, not a
    permission-gated view of the branch object itself. Found and fixed
    while wiring up the actual cross-branch flow in the frontend, not
    hypothetically — see docs/ClinicNet-Phase2-Frontend-Prompt.md.
    """

    queryset = Branch.objects.filter(status=BranchStatus.ACTIVE)
    serializer_class = BranchDirectorySerializer
    permission_classes = [IsAuthenticated]


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
