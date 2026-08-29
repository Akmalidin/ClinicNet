from rest_framework.permissions import BasePermission

from apps.accounts.rbac import has_any_permission, has_permission

# Actions where DRF will fetch a specific object and call
# has_object_permission — real authorization (including the "own" bypass)
# happens there. list/create/available_slots never reach an object, so
# has_permission has to be the one gating them.
_COLLECTION_ACTIONS = {"list", "create", "available_slots"}


class HasReferralPermission(BasePermission):
    """RBAC for Referral — needs its own class because a Referral has TWO
    branches (from_branch/to_branch), unlike the single-.branch resources
    apps.accounts.permissions.HasBranchPermission is built for.

    Keyed by `view.action` (DRF ViewSet action name — "list", "create",
    "schedule", "decline", ...), not by HTTP method: a custom @action and
    the plain create both arrive as POST, so the method alone can't tell
    them apart.

    "Видит/действует над своим" (the doctor who sent it or the one it's
    addressed to) is a baseline, not a branch_scope grant — it always
    passes at the object level, matching the referrals.view/
    referrals.manage design confirmed for Phase 2 (see
    docs/PHASE2-REFERRALS-DESIGN.md). Regression-tested: `has_permission`
    must NOT require `referrals.manage` up front for detail actions like
    decline/schedule/complete, or a doctor with only referrals.view would
    be 403'd before ever reaching the "own" check in
    has_object_permission — see apps.referrals.tests.
    """

    def _required_code(self, view):
        required = getattr(view, "required_permission", None)
        if isinstance(required, dict):
            return required.get(getattr(view, "action", None))
        return required

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        action = getattr(view, "action", None)
        if action not in _COLLECTION_ACTIONS:
            # Object-level action — has_object_permission (below) does the
            # real check once the specific Referral is fetched.
            return True
        code = self._required_code(view)
        if not code:
            return True
        return has_any_permission(request.user, code)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user == obj.from_doctor or (obj.to_doctor_id and user == obj.to_doctor):
            return True
        code = self._required_code(view)
        if not code:
            return True
        return has_permission(user, code, obj.from_branch) or has_permission(user, code, obj.to_branch)
