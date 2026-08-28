from datetime import time

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.branches.models import Branch, StaffBranchAssignment, Weekday

from .models import BranchScope, Permission, Role, RolePermission, User, UserRole
from .rbac import branches_for_permission, has_any_permission, has_permission


class RBACScopeTests(TenantTestCase):
    """RBAC v2: role x permission x branch scope (Phase 1 core requirement)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        self.permission = Permission.objects.create(code="appointment.view", category="scheduling")
        self.role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=self.role, permission=self.permission)

    def _grant(self, user, branch_scope, branches=None):
        ur = UserRole.objects.create(user=user, role=self.role, branch_scope=branch_scope)
        if branches:
            ur.branches.set(branches)
        return ur

    def test_all_scope_sees_every_branch(self):
        user = User.objects.create(username="admin1")
        self._grant(user, BranchScope.ALL)

        self.assertTrue(has_permission(user, "appointment.view", self.branch_a))
        self.assertTrue(has_permission(user, "appointment.view", self.branch_b))
        self.assertTrue(has_permission(user, "appointment.view", None))
        self.assertEqual(
            set(branches_for_permission(user, "appointment.view")),
            {self.branch_a, self.branch_b},
        )

    def test_own_branch_scope_follows_staff_assignment(self):
        user = User.objects.create(username="doc1")
        self._grant(user, BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=user, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )

        self.assertTrue(has_permission(user, "appointment.view", self.branch_a))
        self.assertFalse(has_permission(user, "appointment.view", self.branch_b))
        # Network-wide action (no branch context) never satisfied by own_branch scope.
        self.assertFalse(has_permission(user, "appointment.view", None))
        self.assertEqual(set(branches_for_permission(user, "appointment.view")), {self.branch_a})

    def test_specific_branches_scope(self):
        user = User.objects.create(username="doc2")
        self._grant(user, BranchScope.SPECIFIC_BRANCHES, branches=[self.branch_b])

        self.assertFalse(has_permission(user, "appointment.view", self.branch_a))
        self.assertTrue(has_permission(user, "appointment.view", self.branch_b))
        self.assertEqual(set(branches_for_permission(user, "appointment.view")), {self.branch_b})

    def test_inactive_grant_is_ignored(self):
        user = User.objects.create(username="doc3")
        ur = self._grant(user, BranchScope.ALL)
        ur.is_active = False
        ur.save()

        self.assertFalse(has_permission(user, "appointment.view", self.branch_a))
        self.assertFalse(has_any_permission(user, "appointment.view"))

    def test_unrelated_permission_not_granted(self):
        user = User.objects.create(username="doc4")
        self._grant(user, BranchScope.ALL)

        self.assertFalse(has_permission(user, "branch.manage", self.branch_a))

    def test_superuser_bypasses_rbac(self):
        user = User.objects.create(username="root", is_superuser=True)
        self.assertTrue(has_permission(user, "anything.at.all", self.branch_a))
        self.assertTrue(has_any_permission(user, "anything.at.all"))


class BranchScopedAPITests(TenantTestCase):
    """End-to-end: DRF list endpoints correctly scope by branch, matching
    the manual smoke test run against a real tenant schema during development.
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        view_perm = Permission.objects.create(code="branch.view", category="branches")
        schedule_perm = Permission.objects.create(code="branch.schedule.view", category="branches")
        doctor_role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=doctor_role, permission=view_perm)
        RolePermission.objects.create(role=doctor_role, permission=schedule_perm)

        self.dr_single = User.objects.create(username="dr_single")
        self.dr_single.set_password("pass12345")
        self.dr_single.save()
        UserRole.objects.create(user=self.dr_single, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.dr_single, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.dr_single)
        # TenantMainMiddleware resolves the schema from the Host header on
        # every request. Without it, the request falls through to the
        # public schema (empty urls_public.py -> 404) instead of this
        # test's tenant — and, worse, leaves the DB connection pinned to
        # the public schema for any query made later in the test. Always
        # address requests to the tenant domain TenantTestCase set up.
        self.tenant_host = self.domain.domain

    def _get(self, path):
        return self.client_api.get(path, HTTP_HOST=self.tenant_host)

    def test_branch_list_scoped_without_explicit_filter(self):
        """Regression test: an own_branch-scoped user must NOT be 403'd on a
        bare list request just because no ?branch= filter was supplied."""
        response = self._get("/api/v1/branches/")
        self.assertEqual(response.status_code, 200)
        codes = {row["code"] for row in response.json()}
        self.assertEqual(codes, {"a"})

    def test_branch_list_explicit_filter_out_of_scope_is_forbidden(self):
        response = self._get(f"/api/v1/branch-assignments/?branch={self.branch_b.pk}")
        self.assertEqual(response.status_code, 403)
