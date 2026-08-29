"""RBAC v2: role x permission x branch scope.

Single source of truth for "can this user do X in this branch". Keeping the
logic in one place means the DRF permission class, the admin, and any
management command all agree on the same rules.
"""
from __future__ import annotations

from typing import Optional

from .models import BranchScope, UserRole


def has_permission(user, code: str, branch=None) -> bool:
    """Return True if `user` holds permission `code`, in the context of `branch`.

    - branch=None means a network-wide action (e.g. a consolidated report
      across all branches): only an ALL-scope grant satisfies it.
    - branch=<Branch instance>: OWN_BRANCH and SPECIFIC_BRANCHES grants are
      also checked against that branch.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    from apps.branches.models import StaffBranchAssignment

    user_roles = (
        UserRole.objects.filter(user=user, is_active=True, role__permissions__code=code)
        .select_related("role")
        .prefetch_related("branches")
        .distinct()
    )

    own_branches_cache: Optional[set] = None

    for user_role in user_roles:
        if user_role.branch_scope == BranchScope.ALL:
            return True

        if branch is None:
            # Network-wide action: only ALL-scope grants (handled above) qualify.
            continue

        if user_role.branch_scope == BranchScope.SPECIFIC_BRANCHES:
            if any(b.pk == branch.pk for b in user_role.branches.all()):
                return True

        elif user_role.branch_scope == BranchScope.OWN_BRANCH:
            if own_branches_cache is None:
                own_branches_cache = set(
                    StaffBranchAssignment.objects.filter(
                        staff=user, is_active=True
                    ).values_list("branch_id", flat=True)
                )
            if branch.pk in own_branches_cache:
                return True

    return False


def has_any_permission(user, code: str) -> bool:
    """True if `user` holds `code` in ANY branch scope (no branch context).

    Use for resources that aren't inherently tied to one branch (e.g. the
    Patient record itself, which Phase 2 makes network-wide) — combine with
    `branches_for_permission` to filter what the user actually sees.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return UserRole.objects.filter(
        user=user, is_active=True, role__permissions__code=code
    ).exists()


def branches_for_permission(user, code: str):
    """Return the queryset of Branch objects `user` holds `code` in.

    Useful for filtering list views ("show me appointments only in branches
    I'm allowed to see") without an extra round trip per branch.
    """
    from apps.branches.models import Branch, StaffBranchAssignment

    if user is None or not getattr(user, "is_authenticated", False):
        return Branch.objects.none()
    if getattr(user, "is_superuser", False):
        return Branch.objects.all()

    user_roles = (
        UserRole.objects.filter(user=user, is_active=True, role__permissions__code=code)
        .prefetch_related("branches")
        .distinct()
    )

    if any(ur.branch_scope == BranchScope.ALL for ur in user_roles):
        return Branch.objects.all()

    branch_ids = set()
    for ur in user_roles:
        if ur.branch_scope == BranchScope.SPECIFIC_BRANCHES:
            branch_ids.update(ur.branches.values_list("pk", flat=True))
        elif ur.branch_scope == BranchScope.OWN_BRANCH:
            branch_ids.update(
                StaffBranchAssignment.objects.filter(
                    staff=user, is_active=True
                ).values_list("branch_id", flat=True)
            )

    return Branch.objects.filter(pk__in=branch_ids)


def users_with_permission(branch, code: str):
    """Reverse of `branches_for_permission`: which users hold `code` for
    `branch`? Used for "who's responsible for this branch" lookups (e.g.
    apps.referrals' escalate_stale_referrals — who to notify about a
    branch's stalled referrals). Superusers are deliberately NOT included
    here: this is "who should get paged", not an access check.
    """
    from django.db.models import Q

    from .models import User

    if branch is None:
        return User.objects.none()

    from apps.branches.models import StaffBranchAssignment

    own_branch_staff_ids = set(
        StaffBranchAssignment.objects.filter(branch=branch, is_active=True).values_list(
            "staff_id", flat=True
        )
    )

    return User.objects.filter(
        Q(user_roles__is_active=True, user_roles__role__permissions__code=code)
        & (
            Q(user_roles__branch_scope=BranchScope.ALL)
            | Q(
                user_roles__branch_scope=BranchScope.SPECIFIC_BRANCHES,
                user_roles__branches=branch,
            )
            | Q(user_roles__branch_scope=BranchScope.OWN_BRANCH, pk__in=own_branch_staff_ids)
        )
    ).distinct()
