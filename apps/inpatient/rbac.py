"""Department-scoped RBAC — one level deeper than apps.accounts.rbac's
Branch scoping, deliberately kept OUTSIDE that module (decided explicitly
at the start of Phase 4, not to disturb the foundation every other phase
relies on).

The trick that makes this work with zero changes to apps.accounts: a
UserRole granting an inpatient permission code with `branch_scope=
SPECIFIC_BRANCHES` and NO branches attached already resolves to "reaches
no branches at all" via the existing `branches_for_permission` — that's
just how SPECIFIC_BRANCHES already behaves. Provisioning a department-only
role (nurse, department-head) that way means the branch-wide fallback
below (see `departments_for_permission`) legitimately contributes nothing
for that user, and their only source of visible departments becomes
`StaffDepartmentAssignment` — precisely "sees only their own department",
without a single new concept in the branch-scoping code itself. A
branch-wide role (doctor, branch-admin, network-admin) keeps its existing
OWN_BRANCH/ALL grant and sees every department in its reachable branch(es),
same as it already sees every Visit/Appointment there — deliberately: this
project doesn't restrict doctors to one department, only nurses/department
heads (see seed_rbac.py's comments on this).
"""
from __future__ import annotations

from apps.accounts.rbac import branches_for_permission, has_any_permission

from .models import Department, StaffDepartmentAssignment


def departments_for_permission(user, code: str):
    """Return the queryset of Department objects `user` holds `code` in —
    union of (a) every department in a branch reached via the ordinary
    branch-level grant, and (b) departments the user is explicitly
    assigned to via StaffDepartmentAssignment."""
    if user is None or not getattr(user, "is_authenticated", False):
        return Department.objects.none()
    if getattr(user, "is_superuser", False):
        return Department.objects.all()
    if not has_any_permission(user, code):
        return Department.objects.none()

    branch_qs = branches_for_permission(user, code)
    dept_ids = set(Department.objects.filter(branch__in=branch_qs).values_list("pk", flat=True))
    dept_ids |= set(
        StaffDepartmentAssignment.objects.filter(staff=user, is_active=True).values_list(
            "department_id", flat=True
        )
    )
    return Department.objects.filter(pk__in=dept_ids)
