from datetime import date, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, User, UserRole
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
from apps.patients.models import Patient

from .models import (
    BranchPriceOverride,
    InsurancePolicy,
    InsuranceProvider,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    PaymentKind,
    Service,
)


class InvoiceModelTests(TenantTestCase):
    """total_amount/paid_total/balance_due/is_paid are computed, not
    stored — the whole point of "деньги должны сходиться": these tests
    prove the derivation itself is correct, independent of the API layer.
    """

    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.cashier = User.objects.create(username="cashier")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.invoice = Invoice.objects.create(
            patient=self.patient, branch=self.branch, issued_by=self.cashier,
        )

    def test_total_amount_sums_lines(self):
        InvoiceLine.objects.create(invoice=self.invoice, description="Приём", quantity=1, unit_price=Decimal("500"))
        InvoiceLine.objects.create(invoice=self.invoice, description="Анестезия", quantity=2, unit_price=Decimal("100"))
        self.assertEqual(self.invoice.total_amount, Decimal("700"))

    def test_empty_invoice_totals_are_zero(self):
        self.assertEqual(self.invoice.total_amount, Decimal("0"))
        self.assertEqual(self.invoice.paid_total, Decimal("0"))
        self.assertEqual(self.invoice.balance_due, Decimal("0"))

    def test_issue_requires_at_least_one_line(self):
        with self.assertRaises(ValidationError):
            self.invoice.issue()

    def test_issue_then_cannot_add_lines(self):
        InvoiceLine.objects.create(invoice=self.invoice, description="Приём", quantity=1, unit_price=Decimal("500"))
        self.invoice.issue()
        line = InvoiceLine(invoice=self.invoice, description="Поздняя позиция", quantity=1, unit_price=Decimal("10"))
        with self.assertRaises(ValidationError):
            line.full_clean()

    def test_paid_total_nets_refunds(self):
        InvoiceLine.objects.create(invoice=self.invoice, description="Приём", quantity=1, unit_price=Decimal("1000"))
        self.invoice.issue()
        Payment.objects.create(
            invoice=self.invoice, branch=self.branch, received_by=self.cashier,
            kind=PaymentKind.PAYMENT, amount=Decimal("1000"),
        )
        self.assertTrue(self.invoice.is_paid)
        Payment.objects.create(
            invoice=self.invoice, branch=self.branch, received_by=self.cashier,
            kind=PaymentKind.REFUND, amount=Decimal("300"),
        )
        self.assertEqual(self.invoice.paid_total, Decimal("700"))
        self.assertEqual(self.invoice.balance_due, Decimal("300"))
        self.assertFalse(self.invoice.is_paid)

    def test_cannot_reopen_cancelled_invoice(self):
        self.invoice.status = InvoiceStatus.CANCELLED
        self.invoice.save()
        self.invoice.status = InvoiceStatus.DRAFT
        with self.assertRaises(ValidationError):
            self.invoice.full_clean()

    def test_cancel_is_a_no_op_once_terminal(self):
        self.invoice.cancel()
        self.assertFalse(self.invoice.cancel())

    def test_cancel_refuses_when_money_already_paid(self):
        InvoiceLine.objects.create(invoice=self.invoice, description="Приём", quantity=1, unit_price=Decimal("500"))
        self.invoice.issue()
        Payment.objects.create(
            invoice=self.invoice, branch=self.branch, received_by=self.cashier,
            kind=PaymentKind.PAYMENT, amount=Decimal("500"),
        )
        with self.assertRaises(ValidationError):
            self.invoice.cancel()

    def test_payment_amount_must_be_positive(self):
        payment = Payment(
            invoice=self.invoice, branch=self.branch, received_by=self.cashier, amount=Decimal("0"),
        )
        with self.assertRaises(ValidationError):
            payment.full_clean()


class InvoiceAPITests(TenantTestCase):
    """End-to-end over real HTTP + RBAC — same rigor as apps.referrals/
    apps.diagnostics: branch isolation, double-payment/overpay guards,
    and the cashier role's actual grants, not just what the model allows."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        view_perm = Permission.objects.create(code="finance.view", category="finance")
        manage_perm = Permission.objects.create(code="finance.manage", category="finance")
        cashier_role = Role.objects.create(name="Кассир", codename="cashier")
        RolePermission.objects.create(role=cashier_role, permission=view_perm)
        RolePermission.objects.create(role=cashier_role, permission=manage_perm)
        doctor_role = Role.objects.create(name="Врач", codename="doctor")  # deliberately no finance.*

        self.cashier_a = User.objects.create(username="cashier_a")
        UserRole.objects.create(user=self.cashier_a, role=cashier_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.cashier_a, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.cashier_b = User.objects.create(username="cashier_b")
        UserRole.objects.create(user=self.cashier_b, role=cashier_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.cashier_b, branch=self.branch_b, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.doctor = User.objects.create(username="doc")
        UserRole.objects.create(user=self.doctor, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.doctor, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _issued_invoice(self, branch, cashier, total="1000"):
        client = self._client_for(cashier)
        create = client.post(
            "/api/v1/invoices/",
            {"patient": self.patient.pk, "branch": branch.pk},
            HTTP_HOST=self.host,
        )
        self.assertEqual(create.status_code, 201, create.data)
        invoice_id = create.data["id"]
        client.post(
            f"/api/v1/invoices/{invoice_id}/add_line/",
            {"description": "Приём", "quantity": 1, "unit_price": total},
            HTTP_HOST=self.host,
        )
        issue = client.post(f"/api/v1/invoices/{invoice_id}/issue/", HTTP_HOST=self.host)
        self.assertEqual(issue.status_code, 200, issue.data)
        return invoice_id

    def test_doctor_cannot_access_finance_api(self):
        client = self._client_for(self.doctor)
        response = client.get("/api/v1/invoices/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 403)
        response = client.post(
            "/api/v1/invoices/", {"patient": self.patient.pk, "branch": self.branch_a.pk}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_action_responses_reflect_the_just_made_change(self):
        """Regression test: get_object() prefetches lines/payments via
        get_queryset() BEFORE an action mutates them. Caught live (not by
        this suite originally) as add_line's response body showing the
        correct total_amount (a re-aggregating property) next to a stale,
        empty `lines` array — the response's own nested lines/payments
        have to actually reflect what the action just did, not just the
        computed totals."""
        client = self._client_for(self.cashier_a)
        create = client.post(
            "/api/v1/invoices/", {"patient": self.patient.pk, "branch": self.branch_a.pk}, HTTP_HOST=self.host,
        )
        invoice_id = create.data["id"]

        add = client.post(
            f"/api/v1/invoices/{invoice_id}/add_line/",
            {"description": "Приём", "quantity": 1, "unit_price": "500"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(len(add.data["lines"]), 1, add.data)
        self.assertEqual(add.data["lines"][0]["description"], "Приём")

        issue = client.post(f"/api/v1/invoices/{invoice_id}/issue/", HTTP_HOST=self.host)
        self.assertEqual(len(issue.data["lines"]), 1, issue.data)

        pay = client.post(
            f"/api/v1/invoices/{invoice_id}/pay/", {"kind": "payment", "amount": "500"}, HTTP_HOST=self.host,
        )
        self.assertEqual(len(pay.data["payments"]), 1, pay.data)
        self.assertEqual(pay.data["payments"][0]["amount"], "500.00")

    def test_cashier_b_cannot_see_branch_a_invoice(self):
        invoice_id = self._issued_invoice(self.branch_a, self.cashier_a)
        client_b = self._client_for(self.cashier_b)

        listing = client_b.get("/api/v1/invoices/", HTTP_HOST=self.host)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row["id"] for row in listing.json()], [])

        detail = client_b.get(f"/api/v1/invoices/{invoice_id}/", HTTP_HOST=self.host)
        self.assertEqual(detail.status_code, 404)

        pay = client_b.post(
            f"/api/v1/invoices/{invoice_id}/pay/",
            {"kind": "payment", "amount": "1000"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(pay.status_code, 404)

    def test_full_payment_marks_invoice_paid(self):
        invoice_id = self._issued_invoice(self.branch_a, self.cashier_a, total="1000")
        client = self._client_for(self.cashier_a)
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/pay/",
            {"kind": "payment", "amount": "1000", "method": "cash"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["is_paid"])
        self.assertEqual(response.data["balance_due"], "0.00")

    def test_double_payment_on_fully_paid_invoice_is_rejected(self):
        """The Phase 3 checklist's equivalent of the Phase 2 'result/ on a
        closed LabOrder' check: a second payment attempt must 400, not
        silently create a duplicate Payment row."""
        invoice_id = self._issued_invoice(self.branch_a, self.cashier_a, total="1000")
        client = self._client_for(self.cashier_a)
        first = client.post(
            f"/api/v1/invoices/{invoice_id}/pay/", {"kind": "payment", "amount": "1000"}, HTTP_HOST=self.host,
        )
        self.assertEqual(first.status_code, 201)

        second = client.post(
            f"/api/v1/invoices/{invoice_id}/pay/", {"kind": "payment", "amount": "1000"}, HTTP_HOST=self.host,
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Payment.objects.filter(invoice_id=invoice_id).count(), 1)

    def test_overpayment_beyond_balance_due_is_rejected(self):
        invoice_id = self._issued_invoice(self.branch_a, self.cashier_a, total="1000")
        client = self._client_for(self.cashier_a)
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/pay/", {"kind": "payment", "amount": "1500"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)

    def test_refund_larger_than_paid_is_rejected(self):
        invoice_id = self._issued_invoice(self.branch_a, self.cashier_a, total="1000")
        client = self._client_for(self.cashier_a)
        client.post(f"/api/v1/invoices/{invoice_id}/pay/", {"kind": "payment", "amount": "400"}, HTTP_HOST=self.host)
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/pay/", {"kind": "refund", "amount": "500"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)

    def test_payment_on_draft_invoice_is_rejected(self):
        client = self._client_for(self.cashier_a)
        create = client.post(
            "/api/v1/invoices/", {"patient": self.patient.pk, "branch": self.branch_a.pk}, HTTP_HOST=self.host,
        )
        invoice_id = create.data["id"]
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/pay/", {"kind": "payment", "amount": "100"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 400)

    def test_network_report_scopes_by_branch(self):
        invoice_id = self._issued_invoice(self.branch_a, self.cashier_a, total="1000")
        client_a = self._client_for(self.cashier_a)
        client_a.post(f"/api/v1/invoices/{invoice_id}/pay/", {"kind": "payment", "amount": "1000"}, HTTP_HOST=self.host)

        report_a = client_a.get("/api/v1/finance/report/", HTTP_HOST=self.host)
        self.assertEqual(report_a.status_code, 200)
        branches_seen = {row["branch_id"] for row in report_a.data["by_branch"]}
        self.assertEqual(branches_seen, {self.branch_a.pk})

        client_b = self._client_for(self.cashier_b)
        report_b = client_b.get("/api/v1/finance/report/", HTTP_HOST=self.host)
        self.assertEqual(report_b.data["by_branch"], [])
        self.assertEqual(Decimal(report_b.data["network_total"]), Decimal("0"))


class ServicePricingModelTests(TenantTestCase):
    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")
        self.service = Service.objects.create(name="Консультация", code="consult", base_price=Decimal("500"))

    def test_price_for_falls_back_to_base_price(self):
        self.assertEqual(self.service.price_for(self.branch_a), Decimal("500"))

    def test_price_for_uses_branch_override(self):
        BranchPriceOverride.objects.create(service=self.service, branch=self.branch_a, price=Decimal("650"))
        self.assertEqual(self.service.price_for(self.branch_a), Decimal("650"))
        # Branch B has no override — still the network base price.
        self.assertEqual(self.service.price_for(self.branch_b), Decimal("500"))

    def test_only_one_override_per_service_branch(self):
        BranchPriceOverride.objects.create(service=self.service, branch=self.branch_a, price=Decimal("650"))
        with self.assertRaises(Exception):
            BranchPriceOverride.objects.create(service=self.service, branch=self.branch_a, price=Decimal("700"))


class ServicePricingAPITests(TenantTestCase):
    """RBAC split: pricing.manage needs ALL scope (network catalog),
    pricing.override is branch-scoped (per-branch exceptions) — and the
    checklist's explicit case: a service billed at a branch with an
    override must invoice at the LOCAL price, not the network base."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Филиал А", code="a")
        self.branch_b = Branch.objects.create(name="Филиал Б", code="b")

        manage_perm = Permission.objects.create(code="pricing.manage", category="finance")
        override_perm = Permission.objects.create(code="pricing.override", category="finance")
        finance_view = Permission.objects.create(code="finance.view", category="finance")
        finance_manage = Permission.objects.create(code="finance.manage", category="finance")

        network_admin_role = Role.objects.create(name="Администратор сети", codename="network-admin")
        RolePermission.objects.create(role=network_admin_role, permission=manage_perm)

        branch_admin_role = Role.objects.create(name="Администратор филиала", codename="branch-admin")
        RolePermission.objects.create(role=branch_admin_role, permission=override_perm)

        cashier_role = Role.objects.create(name="Кассир", codename="cashier")
        RolePermission.objects.create(role=cashier_role, permission=finance_view)
        RolePermission.objects.create(role=cashier_role, permission=finance_manage)

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
        # A branch-admin is NOT automatically network-wide, even though
        # the role holds most other .manage codes elsewhere — pricing.manage
        # itself isn't even granted to this role (see seed_rbac.py).

        self.cashier_a = User.objects.create(username="cashier_a")
        UserRole.objects.create(user=self.cashier_a, role=cashier_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.cashier_a, branch=self.branch_a, weekday=Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(18, 0),
        )

        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_network_admin_can_create_service(self):
        client = self._client_for(self.network_admin)
        response = client.post(
            "/api/v1/services/", {"name": "Консультация", "code": "consult", "base_price": "500"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_branch_admin_cannot_create_service(self):
        """own_branch scope must not satisfy pricing.manage — editing the
        network catalog isn't a branch-level action, however many other
        .manage codes this role otherwise holds."""
        client = self._client_for(self.branch_admin_a)
        response = client.post(
            "/api/v1/services/", {"name": "Консультация", "code": "consult", "base_price": "500"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_branch_admin_can_override_own_branch_price(self):
        service = Service.objects.create(name="Консультация", code="consult", base_price=Decimal("500"))
        client = self._client_for(self.branch_admin_a)
        response = client.post(
            "/api/v1/price-overrides/",
            {"service": service.pk, "branch": self.branch_a.pk, "price": "650"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_branch_admin_cannot_override_other_branch_price(self):
        service = Service.objects.create(name="Консультация", code="consult", base_price=Decimal("500"))
        client = self._client_for(self.branch_admin_a)
        response = client.post(
            "/api/v1/price-overrides/",
            {"service": service.pk, "branch": self.branch_b.pk, "price": "650"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_invoice_line_from_service_bills_at_local_override_price(self):
        """The Phase 3 checklist's core (b) case: a service with a
        branch-specific override invoices at the LOCAL price, not the
        network base."""
        service = Service.objects.create(name="Консультация", code="consult", base_price=Decimal("500"))
        BranchPriceOverride.objects.create(service=service, branch=self.branch_a, price=Decimal("650"))

        client = self._client_for(self.cashier_a)
        create = client.post(
            "/api/v1/invoices/", {"patient": self.patient.pk, "branch": self.branch_a.pk}, HTTP_HOST=self.host,
        )
        invoice_id = create.data["id"]
        add = client.post(
            f"/api/v1/invoices/{invoice_id}/add_line/", {"service": service.pk, "quantity": 1}, HTTP_HOST=self.host,
        )
        self.assertEqual(add.status_code, 201, add.data)
        self.assertEqual(add.data["lines"][0]["unit_price"], "650.00")
        self.assertEqual(add.data["lines"][0]["description"], "Консультация")
        self.assertEqual(add.data["total_amount"], "650.00")

    def test_invoice_line_from_service_without_override_bills_network_price(self):
        service = Service.objects.create(name="Рентген", code="xray", base_price=Decimal("300"))
        client = self._client_for(self.cashier_a)
        create = client.post(
            "/api/v1/invoices/", {"patient": self.patient.pk, "branch": self.branch_a.pk}, HTTP_HOST=self.host,
        )
        invoice_id = create.data["id"]
        add = client.post(
            f"/api/v1/invoices/{invoice_id}/add_line/", {"service": service.pk}, HTTP_HOST=self.host,
        )
        self.assertEqual(add.data["lines"][0]["unit_price"], "300.00")

    def test_forged_price_on_service_line_is_ignored(self):
        """Sending a client-supplied unit_price alongside `service` must
        never override the server-resolved catalog price — same "own
        never client-supplied" reasoning as Referral.from_doctor."""
        service = Service.objects.create(name="Консультация", code="consult", base_price=Decimal("500"))
        client = self._client_for(self.cashier_a)
        create = client.post(
            "/api/v1/invoices/", {"patient": self.patient.pk, "branch": self.branch_a.pk}, HTTP_HOST=self.host,
        )
        invoice_id = create.data["id"]
        add = client.post(
            f"/api/v1/invoices/{invoice_id}/add_line/",
            {"service": service.pk, "unit_price": "1"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(add.data["lines"][0]["unit_price"], "500.00")


class InsurancePolicyModelTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.cashier = User.objects.create(username="cashier")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.provider = InsuranceProvider.objects.create(name="СтомСтрах", code="stomstrakh")

    def _policy(self, **overrides):
        defaults = dict(
            patient=self.patient, provider=self.provider, policy_number="POL-1",
            coverage_percent=100, coverage_limit=Decimal("10000"),
        )
        defaults.update(overrides)
        return InsurancePolicy.objects.create(**defaults)

    def test_is_valid_on_respects_date_range(self):
        policy = self._policy(valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31))
        self.assertTrue(policy.is_valid_on(date(2026, 6, 1)))
        self.assertFalse(policy.is_valid_on(date(2025, 12, 31)))
        self.assertFalse(policy.is_valid_on(date(2027, 1, 1)))

    def test_inactive_policy_is_never_valid(self):
        policy = self._policy(is_active=False)
        self.assertFalse(policy.is_valid_on(date.today()))

    def test_used_amount_excludes_draft_and_cancelled(self):
        policy = self._policy()
        draft = Invoice.objects.create(patient=self.patient, branch=self.branch, issued_by=self.cashier, insurance_policy=policy)
        InvoiceLine.objects.create(invoice=draft, description="Приём", quantity=1, unit_price=Decimal("100"))
        # draft — issue() not called, so insurance_covered_amount is still 0 anyway,
        # but exercise the exclusion logic directly:
        draft.insurance_covered_amount = Decimal("100")
        draft.save(update_fields=["insurance_covered_amount"])
        self.assertEqual(policy.used_amount, Decimal("0"))

        draft.status = InvoiceStatus.CANCELLED
        draft.save(update_fields=["status"])
        self.assertEqual(policy.used_amount, Decimal("0"))

    def test_remaining_limit_after_use(self):
        policy = self._policy(coverage_limit=Decimal("1000"))
        invoice = Invoice.objects.create(
            patient=self.patient, branch=self.branch, issued_by=self.cashier, insurance_policy=policy,
        )
        InvoiceLine.objects.create(invoice=invoice, description="Приём", quantity=1, unit_price=Decimal("400"))
        invoice.issue()
        self.assertEqual(invoice.insurance_covered_amount, Decimal("400"))
        self.assertEqual(policy.remaining_limit, Decimal("600"))


class InvoiceInsuranceSplitTests(TenantTestCase):
    """The Phase 3 checklist's core (c) case: coverage_percent and
    coverage_limit actually split the bill, in the right order across
    multiple invoices, and cancelling frees the limit back up."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")
        self.cashier = User.objects.create(username="cashier")
        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.provider = InsuranceProvider.objects.create(name="СтомСтрах", code="stomstrakh")

    def _invoice_with_line(self, policy, total="1000"):
        invoice = Invoice.objects.create(
            patient=self.patient, branch=self.branch, issued_by=self.cashier, insurance_policy=policy,
        )
        InvoiceLine.objects.create(invoice=invoice, description="Приём", quantity=1, unit_price=Decimal(total))
        return invoice

    def test_split_by_coverage_percent(self):
        policy = InsurancePolicy.objects.create(
            patient=self.patient, provider=self.provider, policy_number="P1",
            coverage_percent=80, coverage_limit=Decimal("10000"),
        )
        invoice = self._invoice_with_line(policy, total="1000")
        invoice.issue()
        self.assertEqual(invoice.insurance_covered_amount, Decimal("800"))
        self.assertEqual(invoice.patient_owed_amount, Decimal("200"))
        self.assertEqual(invoice.balance_due, Decimal("200"))

    def test_split_capped_by_remaining_limit(self):
        policy = InsurancePolicy.objects.create(
            patient=self.patient, provider=self.provider, policy_number="P1",
            coverage_percent=100, coverage_limit=Decimal("500"),
        )
        invoice = self._invoice_with_line(policy, total="1000")
        invoice.issue()
        self.assertEqual(invoice.insurance_covered_amount, Decimal("500"))  # capped, not 1000
        self.assertEqual(invoice.patient_owed_amount, Decimal("500"))

    def test_second_invoice_gets_only_whats_left_of_the_limit(self):
        policy = InsurancePolicy.objects.create(
            patient=self.patient, provider=self.provider, policy_number="P1",
            coverage_percent=100, coverage_limit=Decimal("700"),
        )
        first = self._invoice_with_line(policy, total="500")
        first.issue()
        self.assertEqual(first.insurance_covered_amount, Decimal("500"))

        second = self._invoice_with_line(policy, total="500")
        second.issue()
        # Only 200 left of the 700 limit after the first invoice claimed 500.
        self.assertEqual(second.insurance_covered_amount, Decimal("200"))
        self.assertEqual(second.patient_owed_amount, Decimal("300"))

    def test_cancelling_frees_the_limit_for_the_next_invoice(self):
        policy = InsurancePolicy.objects.create(
            patient=self.patient, provider=self.provider, policy_number="P1",
            coverage_percent=100, coverage_limit=Decimal("500"),
        )
        first = self._invoice_with_line(policy, total="500")
        first.issue()
        self.assertEqual(policy.remaining_limit, Decimal("0"))

        first.cancel()  # no payments made against it yet — allowed
        self.assertEqual(policy.remaining_limit, Decimal("500"))

    def test_expired_policy_rejects_issue(self):
        policy = InsurancePolicy.objects.create(
            patient=self.patient, provider=self.provider, policy_number="P1",
            coverage_percent=100, coverage_limit=Decimal("1000"),
            valid_until=date.today() - timedelta(days=1),
        )
        invoice = self._invoice_with_line(policy, total="500")
        with self.assertRaises(ValidationError):
            invoice.issue()

    def test_is_paid_reflects_only_patient_portion(self):
        """balance_due/is_paid track patient_owed_amount, not
        total_amount — an insurance-covered invoice must not look
        perpetually unpaid at the register just because the insurer's
        share was never collected as a Payment."""
        policy = InsurancePolicy.objects.create(
            patient=self.patient, provider=self.provider, policy_number="P1",
            coverage_percent=80, coverage_limit=Decimal("10000"),
        )
        invoice = self._invoice_with_line(policy, total="1000")
        invoice.issue()
        Payment.objects.create(
            invoice=invoice, branch=self.branch, received_by=self.cashier,
            kind=PaymentKind.PAYMENT, amount=Decimal("200"),  # exactly the patient's share
        )
        self.assertTrue(invoice.is_paid)
        self.assertEqual(invoice.balance_due, Decimal("0"))


class InsuranceAPIRBACTests(TenantTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Филиал А", code="a")

        manage_perm = Permission.objects.create(code="insurance.manage", category="finance")
        view_perm = Permission.objects.create(code="insurance.view", category="finance")
        policy_manage_perm = Permission.objects.create(code="insurance.policy.manage", category="finance")

        network_admin_role = Role.objects.create(name="Администратор сети", codename="network-admin")
        RolePermission.objects.create(role=network_admin_role, permission=manage_perm)

        reception_role = Role.objects.create(name="Ресепшн", codename="receptionist")
        RolePermission.objects.create(role=reception_role, permission=view_perm)
        RolePermission.objects.create(role=reception_role, permission=policy_manage_perm)

        cashier_role = Role.objects.create(name="Кассир", codename="cashier")
        RolePermission.objects.create(role=cashier_role, permission=view_perm)

        doctor_role = Role.objects.create(name="Врач", codename="doctor")

        self.network_admin = User.objects.create(username="net_admin")
        UserRole.objects.create(user=self.network_admin, role=network_admin_role, branch_scope=BranchScope.ALL)

        self.reception = User.objects.create(username="reception")
        UserRole.objects.create(user=self.reception, role=reception_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.reception, branch=self.branch, weekday=Weekday.MONDAY,
            start_time=time(8, 0), end_time=time(18, 0),
        )

        self.cashier = User.objects.create(username="cashier")
        UserRole.objects.create(user=self.cashier, role=cashier_role, branch_scope=BranchScope.OWN_BRANCH)
        StaffBranchAssignment.objects.create(
            staff=self.cashier, branch=self.branch, weekday=Weekday.MONDAY,
            start_time=time(8, 0), end_time=time(18, 0),
        )

        self.doctor = User.objects.create(username="doc")
        UserRole.objects.create(user=self.doctor, role=doctor_role, branch_scope=BranchScope.OWN_BRANCH)

        self.patient = Patient.objects.create(first_name="Тест", last_name="Пациентов")
        self.provider = InsuranceProvider.objects.create(name="СтомСтрах", code="stomstrakh")
        self.host = self.domain.domain

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_network_admin_can_manage_provider_catalog(self):
        client = self._client_for(self.network_admin)
        response = client.post(
            "/api/v1/insurance-providers/", {"name": "СтомСтрах 2", "code": "stomstrakh2"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_reception_cannot_manage_provider_catalog(self):
        """Same shape as pricing.manage — a branch-scoped grant must not
        satisfy the ALL-scope-only network catalog check, even for a
        role that DOES manage patient-level insurance.policy.manage."""
        client = self._client_for(self.reception)
        response = client.post(
            "/api/v1/insurance-providers/", {"name": "СтомСтрах 2", "code": "stomstrakh2"}, HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 403)

    def test_reception_can_create_policy(self):
        client = self._client_for(self.reception)
        response = client.post(
            "/api/v1/insurance-policies/",
            {
                "patient": self.patient.pk, "provider": self.provider.pk, "policy_number": "P-100",
                "coverage_percent": 80, "coverage_limit": "5000",
            },
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_cashier_can_view_but_not_create_policy(self):
        client = self._client_for(self.cashier)
        list_response = client.get("/api/v1/insurance-policies/", HTTP_HOST=self.host)
        self.assertEqual(list_response.status_code, 200)

        create = client.post(
            "/api/v1/insurance-policies/",
            {
                "patient": self.patient.pk, "provider": self.provider.pk, "policy_number": "P-100",
                "coverage_percent": 80, "coverage_limit": "5000",
            },
            HTTP_HOST=self.host,
        )
        self.assertEqual(create.status_code, 403)

    def test_doctor_cannot_view_policies(self):
        client = self._client_for(self.doctor)
        response = client.get("/api/v1/insurance-policies/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 403)

    def test_insurance_provider_reads_are_open_to_any_authenticated_user(self):
        client = self._client_for(self.doctor)
        response = client.get("/api/v1/insurance-providers/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
