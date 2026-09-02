from datetime import timedelta

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone

from .models import Permission, Role, Specialty, User, UserRole
from .permissions import HasNetworkWidePermission
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
        # Same convention again — ChurnAlertsPage.vue's client-side
        # branch guard (Фаза 5, под-модуль 1 frontend).
        data["churn_branches"] = sorted(
            set(branches_for_permission(user, "churn.view").values_list("id", flat=True))
            | set(branches_for_permission(user, "churn.manage").values_list("id", flat=True))
        )
        # Same convention again — WarehouseStockPage.vue's client-side
        # branch guard.
        data["inventory_branches"] = sorted(
            set(branches_for_permission(user, "inventory.view").values_list("id", flat=True))
            | set(branches_for_permission(user, "inventory.stock.manage").values_list("id", flat=True))
        )
        # admission_departments: [id, ...] — DEPARTMENT ids (not branches —
        # one level deeper, see apps.inpatient.rbac's docstring), where this
        # user holds inpatient.admission.manage. Local import, same
        # boundary-crossing convention StaffDirectoryView already uses
        # below: apps.accounts deliberately doesn't import apps.inpatient
        # at module level (decided explicitly at the start of Phase 4).
        # AdmissionIntakePage.vue uses this the same way every other page
        # here uses its *_branches list — decide whether to even show the
        # "Госпитализировать" entry point, and as the client-side guard
        # (never trust that /admissions/intake_options/ alone is enough).
        from apps.inpatient.rbac import departments_for_permission

        data["admission_departments"] = sorted(
            departments_for_permission(user, "inpatient.admission.manage").values_list("id", flat=True)
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


class StaffDirectoryView(APIView):
    """Network-wide staff roster with per-person operational KPIs —
    Персонал сети (frontend). Deliberately its own permission
    (staff.view_network, ALL-scope only via HasNetworkWidePermission) —
    not just finance.view/analytics-shaped, this shows every branch's
    staff and their KPIs at once, which is exactly the kind of
    cross-branch visibility RBAC v2 gates behind an explicit ALL-scope
    grant everywhere else in this project (Service/Product catalogs,
    FinanceReportView's own per-branch breakdown).

    "Персонал" here = any active user holding at least one active,
    non-service-account role (excludes triage-bot — see ROLES in
    seed_rbac.py — a bot isn't staff). Built as one plain view returning
    computed rows, same shape as FinanceReportView, rather than a
    ModelViewSet/Serializer: the interesting fields (KPIs, branches) span
    three other apps' models, not a straight projection of User.

    KPI definitions (found real gaps porting staffhr.html — no
    "license expiry"/"appointments per week"/"conversion" existed
    anywhere in the backend before this; these are the ones actually
    computable from real data, not invented to match the mockup 1:1):
    - appointments_last_7_days: this doctor's Appointment count (any
      status) with starts_at in the trailing 7 days — matches what the
      schedule shows them as booked for.
    - conversion_rate: of their Appointments in the trailing 30 days that
      reached a terminal outcome (completed/cancelled/no_show), the
      share that was actually completed — the clinic's real "did the
      booked visit happen" rate, not a sales-funnel metric (there isn't
      one in this domain). null if there's nothing terminal yet to
      divide by, rather than a misleading 0%.
    - license_status: 'ok' / 'warning' (expires within 30 days) /
      'expired' / null (no license_expires_at on file), derived from
      User.license_expires_at (a plain manually-maintained field, no
      licensing-registry integration — see the model docstring).
    """

    permission_classes = [HasNetworkWidePermission]
    required_permission = "staff.view_network"

    def get(self, request):
        from apps.branches.models import StaffBranchAssignment
        from apps.inpatient.models import StaffDepartmentAssignment
        from apps.scheduling.models import Appointment, AppointmentStatus

        staff = (
            User.objects.filter(user_roles__is_active=True, is_active=True)
            .exclude(user_roles__role__codename="triage-bot")
            .distinct()
            .prefetch_related("specialties", "user_roles__role")
            .order_by("first_name", "last_name")
        )

        now = timezone.now()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        today = now.date()

        rows = []
        for user in staff:
            branch_names = set(
                StaffBranchAssignment.objects.filter(staff=user, is_active=True)
                .values_list("branch__name", flat=True)
            ) | set(
                StaffDepartmentAssignment.objects.filter(staff=user, is_active=True)
                .values_list("department__branch__name", flat=True)
            )

            appointments_week = Appointment.objects.filter(
                doctor=user, starts_at__gte=week_ago, starts_at__lte=now
            ).count()

            terminal = Appointment.objects.filter(
                doctor=user, starts_at__gte=month_ago, starts_at__lte=now,
                status__in=(AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW),
            )
            terminal_total = terminal.count()
            completed = terminal.filter(status=AppointmentStatus.COMPLETED).count()
            conversion_rate = round(completed / terminal_total * 100, 1) if terminal_total else None

            if user.license_expires_at is None:
                license_status = None
            elif user.license_expires_at < today:
                license_status = "expired"
            elif user.license_expires_at <= today + timedelta(days=30):
                license_status = "warning"
            else:
                license_status = "ok"

            rows.append({
                "id": user.pk,
                "name": user.get_full_name() or user.username,
                "job_title": user.job_title,
                "roles": [ur.role.name for ur in user.user_roles.all() if ur.is_active],
                "specialties": [s.name for s in user.specialties.all()],
                "branches": sorted(branch_names),
                "license_expires_at": user.license_expires_at,
                "license_status": license_status,
                "appointments_last_7_days": appointments_week,
                "conversion_rate": conversion_rate,
            })

        return Response(rows)
