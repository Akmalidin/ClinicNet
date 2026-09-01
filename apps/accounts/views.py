from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Permission, Role, Specialty, User, UserRole
from .rbac import branches_for_permission
from .serializers import (
    DoctorSerializer,
    PermissionSerializer,
    RoleSerializer,
    SpecialtySerializer,
    UserRoleSerializer,
    UserSerializer,
)


class MeView(APIView):
    """Who am I, and (for convenience) which branches can I act in per permission."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request):
        user = request.user
        data = UserSerializer(user).data
        data["roles"] = [
            {
                "role": ur.role.name,
                "branch_scope": ur.branch_scope,
                "branches": list(ur.branches.values_list("id", flat=True)),
            }
            for ur in user.user_roles.filter(is_active=True).select_related("role")
        ]
        # Precomputed via the same rbac.branches_for_permission() the
        # backend itself uses to filter — not something the frontend
        # reconstructs from the raw `roles` above (own_branch scope, in
        # particular, depends on StaffBranchAssignment, which isn't in
        # `roles` at all). This is what ReferralQueueWidget.vue's
        # client-side re-check verifies each row against: an independent
        # fetch, not a trust of whatever ReferralViewSet.get_queryset
        # already returned — see its own docstring.
        data["referral_branches"] = sorted(
            set(branches_for_permission(user, "referrals.view").values_list("id", flat=True))
            | set(branches_for_permission(user, "referrals.manage").values_list("id", flat=True))
        )
        # Same precomputed-branch-list convention as referral_branches
        # above — this is what TriageQueueWidget.vue's client-side branch
        # guard verifies each row against (Фаза 5, под-модуль 2 frontend).
        data["triage_branches"] = sorted(
            set(branches_for_permission(user, "triage.view").values_list("id", flat=True))
            | set(branches_for_permission(user, "triage.manage").values_list("id", flat=True))
        )
        return Response(data)


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.prefetch_related("permissions").all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated]


class UserRoleViewSet(viewsets.ModelViewSet):
    queryset = UserRole.objects.select_related("user", "role").prefetch_related("branches").all()
    serializer_class = UserRoleSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(granted_by=self.request.user)


class SpecialtyViewSet(viewsets.ReadOnlyModelViewSet):
    """Catalog of medical specialties — feeds the referral frontend's
    "направить на специальность" picker (ClinicNet-Referrals-Prompt.md,
    section 6, cross-branch flow: specialty -> branch -> doctor)."""

    queryset = Specialty.objects.all()
    serializer_class = SpecialtySerializer
    permission_classes = [IsAuthenticated]


class DoctorViewSet(viewsets.ReadOnlyModelViewSet):
    """Doctors available as a referral target. Not a general staff
    directory — scoped to users holding the 'doctor' role, since a
    referral is always routed to a doctor, never an admin/receptionist.

    ?branch=<id>   only doctors with an active StaffBranchAssignment there
    ?specialty=<code>  only doctors with that specialty
    Both are used together for the cross-branch flow (specialty picked
    first, then branch); ?branch= alone covers the same-branch flow
    (ReferralModal step 5), where the branch is already known from context.
    """

    serializer_class = DoctorSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = (
            User.objects.filter(
                user_roles__role__codename="doctor",
                user_roles__is_active=True,
                is_active=True,
            )
            .distinct()
            .prefetch_related("specialties")
            .order_by("first_name", "last_name")
        )
        branch_id = self.request.query_params.get("branch")
        if branch_id:
            qs = qs.filter(
                branch_assignments__branch_id=branch_id,
                branch_assignments__is_active=True,
            ).distinct()
        specialty = self.request.query_params.get("specialty")
        if specialty:
            qs = qs.filter(specialties__code=specialty).distinct()
        return qs
