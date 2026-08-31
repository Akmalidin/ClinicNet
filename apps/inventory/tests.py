from datetime import time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, User, UserRole
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
from apps.patients.models import Patient
from apps.visits.models import Visit, VisitStatus

from .models import Product, Stock, StockMovement, StockMovementReason
from .services import consume_for_visit


class StockModelTests(TenantTestCase):
    """on_hand_quantity/is_below_minimum are computed from the movement
    ledger, never stored — same "always derived, never a drifting cache"
    principle as apps.finance's Invoice totals. These tests prove the
    derivation itself, independent of the API/service layer.
    """

    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.user = User.objects.create(username="stockkeeper")
        self.product = Product.objects.create(name="Анестетик Ultracain", code="ultracain", unit="уп.")
        self.stock = Stock.objects.create(product=self.product, branch=self.branch, min_quantity=Decimal("5"))

    def test_on_hand_quantity_is_zero_with_no_movements(self):
        self.assertEqual(self.stock.on_hand_quantity, Decimal("0"))

    def test_on_hand_quantity_sums_movements(self):
        StockMovement.objects.create(
            product=self.product, branch=self.branch, quantity_delta=Decimal("20"),
            reason=StockMovementReason.RESTOCK, created_by=self.user,
        )
        StockMovement.objects.create(
            product=self.product, branch=self.branch, quantity_delta=Decimal("-3"),
            reason=StockMovementReason.CONSUMPTION, created_by=self.user,
        )
        self.assertEqual(self.stock.on_hand_quantity, Decimal("17"))

    def test_on_hand_quantity_is_per_branch(self):
        other_branch = Branch.objects.create(name="Филиал Б", code="b")
        Stock.objects.create(product=self.product, branch=other_branch)
        StockMovement.objects.create(
            product=self.product, branch=self.branch, quantity_delta=Decimal("10"),
            reason=StockMovementReason.RESTOCK, created_by=self.user,
        )
        StockMovement.objects.create(
            product=self.product, branch=other_branch, quantity_delta=Decimal("999"),
            reason=StockMovementReason.RESTOCK, created_by=self.user,
        )
        self.assertEqual(self.stock.on_hand_quantity, Decimal("10"))

    def test_is_below_minimum(self):
        StockMovement.objects.create(
            product=self.product, branch=self.branch, quantity_delta=Decimal("3"),
            reason=StockMovementReason.RESTOCK, created_by=self.user,
        )
        self.assertTrue(self.stock.is_below_minimum)
        StockMovement.objects.create(
            product=self.product, branch=self.branch, quantity_delta=Decimal("10"),
            reason=StockMovementReason.RESTOCK, created_by=self.user,
        )
        self.assertFalse(self.stock.is_below_minimum)

    def test_zero_min_quantity_never_alerts(self):
        """min_quantity=0 explicitly means "no alert wanted" — even at
        zero on-hand, is_below_minimum must stay False."""
        no_threshold = Stock.objects.create(
            product=Product.objects.create(name="Перчатки", code="gloves", unit="шт"), branch=self.branch,
        )
        self.assertFalse(no_threshold.is_below_minimum)

    def test_negative_min_quantity_rejected(self):
        stock = Stock(product=self.product, branch=self.branch, min_quantity=Decimal("-1"))
        with self.assertRaises(ValidationError):
            stock.full_clean()


class StockMovementModelTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.user = User.objects.create(username="stockkeeper")
        self.product = Product.objects.create(name="Анестетик", code="anest", unit="уп.")

    def test_zero_delta_rejected(self):
        movement = StockMovement(
            product=self.product, branch=self.branch, quantity_delta=Decimal("0"),
            reason=StockMovementReason.ADJUSTMENT, created_by=self.user,
        )
        with self.assertRaises(ValidationError):
            movement.full_clean()


class ConsumeForVisitServiceTests(TenantTestCase):
    """apps.inventory.services.consume_for_visit — the all-or-nothing
    validation that backs VisitViewSet.close()'s consumed_items."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.other_branch = Branch.objects.create(name="Филиал Б", code="b")
        self.doctor = User.objects.create(username="doc")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.visit = Visit.objects.create(patient=self.patient, doctor=self.doctor, branch=self.branch)

        self.anesthetic = Product.objects.create(name="Анестетик", code="anest", unit="уп.")
        self.stock = Stock.objects.create(product=self.anesthetic, branch=self.branch)
        StockMovement.objects.create(
            product=self.anesthetic, branch=self.branch, quantity_delta=Decimal("10"),
            reason=StockMovementReason.RESTOCK, created_by=self.doctor,
        )

    def test_empty_items_is_a_no_op(self):
        result = consume_for_visit(self.visit, [], self.doctor)
        self.assertEqual(result, [])
        self.assertEqual(self.stock.on_hand_quantity, Decimal("10"))

    def test_consumes_and_records_negative_movement(self):
        result = consume_for_visit(
            self.visit, [{"product": self.anesthetic.pk, "quantity": "3"}], self.doctor
        )
        self.assertEqual(len(result), 1)
        movement = result[0]
        self.assertEqual(movement.quantity_delta, Decimal("-3"))
        self.assertEqual(movement.reason, StockMovementReason.CONSUMPTION)
        self.assertEqual(movement.source_visit, self.visit)
        self.assertEqual(self.stock.on_hand_quantity, Decimal("7"))

    def test_rejects_missing_stock_row_at_branch(self):
        """Consuming a product the visit's branch doesn't track at all —
        no Stock row — must be rejected, not silently create one."""
        other_product = Product.objects.create(name="Бинты", code="bandage", unit="шт")
        with self.assertRaises(ValidationError):
            consume_for_visit(
                self.visit, [{"product": other_product.pk, "quantity": "1"}], self.doctor
            )
        self.assertEqual(StockMovement.objects.filter(product=other_product).count(), 0)

    def test_rejects_insufficient_stock(self):
        with self.assertRaises(ValidationError):
            consume_for_visit(
                self.visit, [{"product": self.anesthetic.pk, "quantity": "999"}], self.doctor
            )
        self.assertEqual(self.stock.on_hand_quantity, Decimal("10"))

    def test_rejects_non_positive_quantity(self):
        with self.assertRaises(ValidationError):
            consume_for_visit(
                self.visit, [{"product": self.anesthetic.pk, "quantity": "0"}], self.doctor
            )

    def test_is_all_or_nothing_across_multiple_items(self):
        """One bad item in the list must not leave a partial write behind
        — the good item's movement must NOT be created either."""
        bandage = Product.objects.create(name="Бинты", code="bandage2", unit="шт")
        # No Stock row for `bandage` at this branch — the second item fails.
        with self.assertRaises(ValidationError):
            consume_for_visit(
                self.visit,
                [
                    {"product": self.anesthetic.pk, "quantity": "2"},
                    {"product": bandage.pk, "quantity": "1"},
                ],
                self.doctor,
            )
        # Nothing recorded at all — not even the valid anesthetic line.
        self.assertEqual(self.stock.on_hand_quantity, Decimal("10"))
        self.assertEqual(StockMovement.objects.filter(reason=StockMovementReason.CONSUMPTION).count(), 0)

    def test_only_consumes_at_the_visits_own_branch(self):
        """A Stock row for the same product exists at another branch —
        must not be touched or substituted for the visit's own branch."""
        other_stock = Stock.objects.create(product=self.anesthetic, branch=self.other_branch)
        StockMovement.objects.create(
            product=self.anesthetic, branch=self.other_branch, quantity_delta=Decimal("50"),
            reason=StockMovementReason.RESTOCK, created_by=self.doctor,
        )
        consume_for_visit(self.visit, [{"product": self.anesthetic.pk, "quantity": "3"}], self.doctor)
        self.assertEqual(self.stock.on_hand_quantity, Decimal("7"))
        self.assertEqual(other_stock.on_hand_quantity, Decimal("50"))


class InventoryAPIRBACTests(TenantTestCase):
    """Network-wide Product catalog (inventory.manage, ALL-scope only —
    HasNetworkWidePermission) vs. branch-scoped Stock/StockMovement
    (inventory.view / inventory.stock.manage, HasBranchPermission) — same
    two-tier shape already used for Service/BranchPriceOverride and
    InsuranceProvider/InsurancePolicy.
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        manage_perm = Permission.objects.create(code="inventory.manage", category="inventory")
        view_perm = Permission.objects.create(code="inventory.view", category="inventory")
        stock_manage_perm = Permission.objects.create(code="inventory.stock.manage", category="inventory")

        network_admin_role = Role.objects.create(name="Администратор сети", codename="network-admin")
        RolePermission.objects.create(role=network_admin_role, permission=manage_perm)
        RolePermission.objects.create(role=network_admin_role, permission=view_perm)
        RolePermission.objects.create(role=network_admin_role, permission=stock_manage_perm)

        branch_admin_role = Role.objects.create(name="Администратор филиала", codename="branch-admin")
        RolePermission.objects.create(role=branch_admin_role, permission=view_perm)
        RolePermission.objects.create(role=branch_admin_role, permission=stock_manage_perm)

        self.network_admin = User.objects.create(username="net_admin")
        UserRole.objects.create(user=self.network_admin, role=network_admin_role, branch_scope=BranchScope.ALL)

        self.branch_admin_a = User.objects.create(username="admin_a")
        UserRole.objects.create(
            user=self.branch_admin_a, role=branch_admin_role, branch_scope=BranchScope.OWN_BRANCH
        )
        StaffBranchAssignment.objects.create(
            staff=self.branch_admin_a, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.branch_admin_b = User.objects.create(username="admin_b")
        UserRole.objects.create(
            user=self.branch_admin_b, role=branch_admin_role, branch_scope=BranchScope.OWN_BRANCH
        )
        StaffBranchAssignment.objects.create(
            staff=self.branch_admin_b, branch=self.branch_b, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.product = Product.objects.create(name="Анестетик", code="anest", unit="уп.")
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    # --- Product catalog: network-wide, ALL-scope only ---

    def test_network_admin_can_create_product(self):
        client = self._client_for(self.network_admin)
        response = client.post(
            "/api/v1/products/", {"name": "Бинты", "code": "bandage", "unit": "шт"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_branch_admin_cannot_create_product(self):
        """own_branch scope must not satisfy inventory.manage — same
        reasoning as pricing.manage/insurance.manage: editing the network
        catalog isn't a branch-level action."""
        client = self._client_for(self.branch_admin_a)
        response = client.post(
            "/api/v1/products/", {"name": "Бинты", "code": "bandage", "unit": "шт"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_any_authenticated_user_can_read_product_catalog(self):
        client = self._client_for(self.branch_admin_a)
        response = client.get("/api/v1/products/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)

    # --- Stock: branch isolation ---

    def test_branch_admin_can_create_stock_at_own_branch(self):
        client = self._client_for(self.branch_admin_a)
        response = client.post(
            "/api/v1/stocks/",
            {"product": self.product.pk, "branch": self.branch_a.pk, "min_quantity": "5"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_branch_admin_cannot_create_stock_at_other_branch(self):
        client = self._client_for(self.branch_admin_a)
        response = client.post(
            "/api/v1/stocks/",
            {"product": self.product.pk, "branch": self.branch_b.pk, "min_quantity": "5"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_branch_admin_cannot_see_other_branchs_stock(self):
        """The checklist's explicit RBAC case, real HTTP request: one
        branch's stock must not be visible from another branch's account."""
        Stock.objects.create(product=self.product, branch=self.branch_a)
        Stock.objects.create(product=self.product, branch=self.branch_b)

        client_a = self._client_for(self.branch_admin_a)
        response = client_a.get("/api/v1/stocks/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        branches_seen = {row["branch"] for row in response.data}
        self.assertEqual(branches_seen, {self.branch_a.pk})

    def test_adjust_creates_movement_and_rejects_negative_result(self):
        stock = Stock.objects.create(product=self.product, branch=self.branch_a)
        client = self._client_for(self.branch_admin_a)

        restock = client.post(
            f"/api/v1/stocks/{stock.pk}/adjust/",
            {"quantity_delta": "10", "reason": "restock"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(restock.status_code, 201, restock.data)
        self.assertEqual(restock.data["on_hand_quantity"], "10.00")

        overdraw = client.post(
            f"/api/v1/stocks/{stock.pk}/adjust/",
            {"quantity_delta": "-999", "reason": "adjustment"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(overdraw.status_code, 400)
        stock.refresh_from_db()
        self.assertEqual(stock.on_hand_quantity, Decimal("10"))

    def test_adjust_at_other_branch_not_visible(self):
        """Same shape as InvoiceViewSet's cross-branch 404s (not 403) —
        get_queryset() already excludes the other branch's Stock row
        entirely, so get_object() can't find it to check at all."""
        stock = Stock.objects.create(product=self.product, branch=self.branch_b)
        client = self._client_for(self.branch_admin_a)
        response = client.post(
            f"/api/v1/stocks/{stock.pk}/adjust/", {"quantity_delta": "10", "reason": "restock"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 404)

    def test_low_stock_scoped_to_own_branch_only(self):
        """The checklist's low-stock-alert case: appears correctly and
        ONLY for the affected branch."""
        low = Stock.objects.create(product=self.product, branch=self.branch_a, min_quantity=Decimal("5"))
        StockMovement.objects.create(
            product=self.product, branch=self.branch_a, quantity_delta=Decimal("2"),
            reason=StockMovementReason.RESTOCK, created_by=self.network_admin,
        )
        no_threshold_product = Product.objects.create(name="Перчатки", code="gloves-low-stock-test", unit="шт")
        ok = Stock.objects.create(product=no_threshold_product, branch=self.branch_a, min_quantity=Decimal("0"))
        # Another branch also below its minimum — must not leak into A's alert list.
        other_low = Stock.objects.create(product=self.product, branch=self.branch_b, min_quantity=Decimal("5"))

        client_a = self._client_for(self.branch_admin_a)
        response = client_a.get("/api/v1/stocks/low_stock/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {low.pk})

        client_b = self._client_for(self.branch_admin_b)
        response_b = client_b.get("/api/v1/stocks/low_stock/", HTTP_HOST=self.host)
        ids_b = {row["id"] for row in response_b.data}
        self.assertEqual(ids_b, {other_low.pk})


class VisitCloseConsumptionIntegrationTests(TenantTestCase):
    """VisitViewSet.close() + consume_for_visit end to end — the
    checklist's explicit case: closing a visit consumes the right
    branch's stock, and leaves another branch's stock untouched.
    """

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")

        view_perm = Permission.objects.create(code="visit.view", category="visits")
        manage_perm = Permission.objects.create(code="visit.manage", category="visits")
        doctor_role = Role.objects.create(name="Врач", codename="doctor")
        RolePermission.objects.create(role=doctor_role, permission=view_perm)
        RolePermission.objects.create(role=doctor_role, permission=manage_perm)

        self.doctor_a = User.objects.create(username="doc_a")
        UserRole.objects.create(user=self.doctor_a, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.doctor_a, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.anesthetic = Product.objects.create(name="Анестетик", code="anest", unit="уп.")
        self.stock_a = Stock.objects.create(product=self.anesthetic, branch=self.branch_a, min_quantity=Decimal("5"))
        self.stock_b = Stock.objects.create(product=self.anesthetic, branch=self.branch_b, min_quantity=Decimal("5"))
        for stock, branch, qty in ((self.stock_a, self.branch_a, "10"), (self.stock_b, self.branch_b, "10")):
            StockMovement.objects.create(
                product=self.anesthetic, branch=branch, quantity_delta=Decimal(qty),
                reason=StockMovementReason.RESTOCK, created_by=self.doctor_a,
            )

        self.visit = Visit.objects.create(patient=self.patient, doctor=self.doctor_a, branch=self.branch_a)
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_close_consumes_only_the_visits_own_branch_stock(self):
        client = self._client_for(self.doctor_a)
        response = client.post(
            f"/api/v1/visits/{self.visit.pk}/close/",
            {"consumed_items": [{"product": self.anesthetic.pk, "quantity": "4"}]},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], VisitStatus.COMPLETED)

        self.assertEqual(self.stock_a.on_hand_quantity, Decimal("6"))
        # Branch B's identical product is untouched.
        self.assertEqual(self.stock_b.on_hand_quantity, Decimal("10"))

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, VisitStatus.COMPLETED)
        self.assertIsNotNone(self.visit.closed_at)

    def test_low_stock_alert_appears_only_for_the_affected_branch_after_close(self):
        client = self._client_for(self.doctor_a)
        response = client.post(
            f"/api/v1/visits/{self.visit.pk}/close/",
            {"consumed_items": [{"product": self.anesthetic.pk, "quantity": "7"}]},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        # 10 - 7 = 3, below min_quantity=5 -> alert for branch A's stock row.
        self.assertTrue(self.stock_a.is_below_minimum)
        self.assertFalse(self.stock_b.is_below_minimum)

        network_view = Permission.objects.get(code="visit.view")
        inv_view = Permission.objects.create(code="inventory.view", category="inventory")
        RolePermission.objects.create(role=Role.objects.get(codename="doctor"), permission=inv_view)
        low_stock = client.get("/api/v1/stocks/low_stock/", HTTP_HOST=self.host)
        ids = {row["id"] for row in low_stock.data}
        self.assertEqual(ids, {self.stock_a.pk})

    def test_close_rejects_when_stock_insufficient_and_visit_stays_open(self):
        client = self._client_for(self.doctor_a)
        response = client.post(
            f"/api/v1/visits/{self.visit.pk}/close/",
            {"consumed_items": [{"product": self.anesthetic.pk, "quantity": "999"}]},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, VisitStatus.IN_PROGRESS)
        self.assertEqual(self.stock_a.on_hand_quantity, Decimal("10"))

    def test_double_close_does_not_double_consume(self):
        """Mirrors the Phase 2 LabOrder result/ double-submit guard: a
        retried close request against an already-closed visit must be
        rejected, not silently record a second round of consumption."""
        client = self._client_for(self.doctor_a)
        first = client.post(
            f"/api/v1/visits/{self.visit.pk}/close/",
            {"consumed_items": [{"product": self.anesthetic.pk, "quantity": "4"}]},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(first.status_code, 200, first.data)

        second = client.post(
            f"/api/v1/visits/{self.visit.pk}/close/",
            {"consumed_items": [{"product": self.anesthetic.pk, "quantity": "4"}]},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(self.stock_a.on_hand_quantity, Decimal("6"))

    def test_close_with_no_consumed_items_just_closes(self):
        client = self._client_for(self.doctor_a)
        response = client.post(
            f"/api/v1/visits/{self.visit.pk}/close/", {}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.stock_a.on_hand_quantity, Decimal("10"))
