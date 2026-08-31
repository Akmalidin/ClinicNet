from rest_framework.permissions import BasePermission

from .rbac import has_any_permission, has_permission


class HasBranchPermission(BasePermission):
    """Generic DRF permission that enforces RBAC v2.

    Views opt in by declaring `required_permission = "appointment.view"`
    (or a per-method dict: `required_permission = {"GET": "...", "POST": "..."}`).

    View-level check (`has_permission`):
    - If a branch is resolvable from the request (`branch` query/body param,
      e.g. filtering or creating a row for a specific branch), the grant is
      checked against exactly that branch.
    - Otherwise (a bare list request — the caller doesn't know yet which
      branches they'll get back) we only require *some* active grant of the
      permission, in any scope, and leave the actual per-row scoping to the
      view's `get_queryset` (see `rbac.branches_for_permission`). Denying
      the whole request here would incorrectly 403 an own_branch/
      specific_branches user just because they didn't (or can't yet) name
      a branch up front.

    Object-level check (`has_object_permission`): always resolves the
    branch from the object's own `.branch` FK, so it needs no request param.
    """

    def _required_code(self, request, view):
        required = getattr(view, "required_permission", None)
        if isinstance(required, dict):
            return required.get(request.method)
        return required

    def _resolve_branch(self, request):
        branch_id = request.query_params.get("branch") or request.data.get("branch")
        if not branch_id:
            return None
        from apps.branches.models import Branch

        return Branch.objects.filter(pk=branch_id).first()

    def has_permission(self, request, view):
        code = self._required_code(request, view)
        if not code:
            return bool(request.user and request.user.is_authenticated)
        branch = self._resolve_branch(request)
        if branch is not None:
            return has_permission(request.user, code, branch)
        return has_any_permission(request.user, code)

    def has_object_permission(self, request, view, obj):
        code = self._required_code(request, view)
        if not code:
            return bool(request.user and request.user.is_authenticated)
        from apps.branches.models import Branch

        branch = obj if isinstance(obj, Branch) else getattr(obj, "branch", None)
        return has_permission(request.user, code, branch)


class HasPermission(BasePermission):
    """Branch-agnostic RBAC check: does the user hold this permission at all,
    in any scope? For a resource that isn't itself branch-scoped (e.g.
    Patient, which has an optional `primary_branch` rather than a required
    `branch`), so `HasBranchPermission`'s object-level `.branch` lookup
    doesn't apply. Pair with `rbac.branches_for_permission` in the view's
    `get_queryset` to filter results down to the branches the user can see.
    """

    def _required_code(self, request, view):
        required = getattr(view, "required_permission", None)
        if isinstance(required, dict):
            return required.get(request.method)
        return required

    def has_permission(self, request, view):
        code = self._required_code(request, view)
        if not code:
            return bool(request.user and request.user.is_authenticated)
        return has_any_permission(request.user, code)


class HasNetworkWidePermission(BasePermission):
    """Requires an ALL-scope grant specifically — `has_any_permission`
    isn't enough here, an own_branch/specific_branches grant must not
    pass, because there's no branch for that scoping to apply *to*.

    For a genuinely network-wide resource with no branch of its own at
    all (e.g. the Service price catalog, apps.finance.models.Service —
    every branch's price for a service is a separate BranchPriceOverride,
    but the catalog entry itself — its name, its base_price — belongs to
    no single branch, so editing it isn't something an own_branch grant
    should be able to do). `has_permission(user, code, branch=None)`
    already encodes exactly this rule (see rbac.has_permission's own
    docstring): only ALL-scope grants satisfy a branch=None check.
    """

    def _required_code(self, request, view):
        required = getattr(view, "required_permission", None)
        if isinstance(required, dict):
            return required.get(request.method)
        return required

    def has_permission(self, request, view):
        code = self._required_code(request, view)
        if not code:
            return bool(request.user and request.user.is_authenticated)
        return has_permission(request.user, code, branch=None)
