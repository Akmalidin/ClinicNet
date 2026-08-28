from datetime import time

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import User

from .models import Branch, StaffBranchAssignment, Weekday


class StaffBranchAssignmentTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.staff = User.objects.create(username="doc")

    def test_valid_shift(self):
        assignment = StaffBranchAssignment(
            staff=self.staff, branch=self.branch, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0),
        )
        assignment.full_clean()  # should not raise

    def test_start_after_end_rejected(self):
        assignment = StaffBranchAssignment(
            staff=self.staff, branch=self.branch, weekday=Weekday.MONDAY,
            start_time=time(17, 0), end_time=time(9, 0),
        )
        with self.assertRaises(ValidationError):
            assignment.full_clean()
