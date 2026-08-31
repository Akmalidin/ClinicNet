from rest_framework.permissions import BasePermission

from apps.accounts.rbac import has_any_permission

from .rbac import departments_for_permission


class HasDepartmentPermission(BasePermission):
    """Department-scoped equivalent of apps.accounts.permissions.
    HasBranchPermission — same shape, one level deeper. View-level check
    is coarse (does the user hold this code at all, in any scope) exactly
    like HasBranchPermission's list-request case; the real row-level
    scoping happens in the view's get_queryset() via
    apps.inpatient.rbac.departments_for_permission. Object-level check
    resolves `obj.department` (or `obj` itself if it IS a Department).
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

    def has_object_permission(self, request, view, obj):
        code = self._required_code(request, view)
        if not code:
            return bool(request.user and request.user.is_authenticated)
        from .models import Department

        department = obj if isinstance(obj, Department) else getattr(obj, "department", None)
        if department is None:
            return False
        return departments_for_permission(request.user, code).filter(pk=department.pk).exists()
