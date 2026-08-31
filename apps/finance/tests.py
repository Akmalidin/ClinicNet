from datetime import time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import BranchScope, Permission, Role, RolePermission, User, UserRole
from apps.branches.models import Branch, StaffBranchAssignment, Weekday
from apps.patients.models import Patient

from .models import Invoice, InvoiceLine, InvoiceStatus, Payment, PaymentKind


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
