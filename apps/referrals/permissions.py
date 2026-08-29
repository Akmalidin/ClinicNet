from rest_framework.permissions import BasePermission

from apps.accounts.rbac import has_permission


class HasReferralPermission(BasePermission):
    """RBAC for Referral — needs its own class because a Referral has TWO
    branches (from_branch/to_branch), unlike the single-.branch resources
    apps.accounts.permissions.HasBranchPermission is built for.

    Design point found while manually verifying the RBAC checklist item
    ("a plain doctor sees only what they sent/received, not the whole
    branch/network queue"): `referrals.view`/`referrals.manage` are NOT
    something a plain doctor needs at all. "Своё" (from_doctor/to_doctor =
    me) is an unconditional baseline — list it, create it, act on it
    (schedule/decline/complete), with no permission grant required, since
    from_doctor is always forced to request.user (see
    ReferralViewSet.perform_create). The two permission codes exist purely
    for the ESCALATION beyond your own: a branch coordinator or network
    admin who needs to see/manage the whole queue holds referrals.view/
    referrals.manage (via UserRole.branch_scope, as everywhere else in
    this project's RBAC). Giving a regular doctor role that grant (even
    at own_branch scope) would leak the whole branch's queue to them,
    which is exactly what this checklist item caught — see
    docs/PHASE2-REFERRALS-DESIGN.md and seed_rbac.py (doctor role does
    NOT include referrals.view/manage; branch-admin and network-admin do).

    Consequently `has_permission` (view-level, no object yet) never gates
    on a permission code — it only checks authentication:
    - list/create/available_slots have no object to check ownership of
      yet; "own" for list is applied in ReferralViewSet.get_queryset
      (which ALSO adds branch-scoped rows for anyone who does hold
      referrals.view/manage), create is inherently "from yourself", and
      available_slots is a harmless read (a doctor's free/busy calendar)
      every referring doctor needs regardless of RBAC.
    - retrieve/update/schedule/decline/complete defer entirely to
      has_object_permission below, once the specific Referral is fetched.
    """

    def _required_code(self, view):
        required = getattr(view, "required_permission", None)
        if isinstance(required, dict):
            return required.get(getattr(view, "action", None))
        return required

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user == obj.from_doctor or (obj.to_doctor_id and user == obj.to_doctor):
            return True
        code = self._required_code(view)
        if not code:
            return True
        return has_permission(user, code, obj.from_branch) or has_permission(user, code, obj.to_branch)
