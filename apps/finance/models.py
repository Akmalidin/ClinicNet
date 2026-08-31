from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"  # line items still editable, no payments yet
    ISSUED = "issued", "Выставлен"  # locked, ready to accept payments
    CANCELLED = "cancelled", "Отменён"


# Same terminal-state pattern as apps.referrals/apps.diagnostics — a
# cancelled invoice's status can't change again.
TERMINAL_STATUSES = (InvoiceStatus.CANCELLED,)

ZERO = Decimal("0")


class Invoice(models.Model):
    """A bill for services rendered — Phase 3's "мультикасса": every
    invoice belongs to exactly one branch's cash register (master plan:
    "каждая касса привязана к филиалу"), and the network-wide report
    (apps.finance.views.FinanceReportView) aggregates across branches by
    querying Payment directly rather than trusting any cached total.

    total_amount/paid_total/balance_due are deliberately NOT stored
    columns — always derived from InvoiceLine and Payment. The whole point
    of an append-only ledger (see Payment's docstring) is that "почему
    касса не сходится" has to be answerable from the actual line items and
    payment history, never from a running number that could silently drift
    out of sync with them.
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="invoices"
    )
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="invoices"
    )
    source_visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        help_text="Приём, из карты которого выставлен счёт — необязателен.",
    )
    issued_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="invoices_issued"
    )
    status = models.CharField(
        max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["patient"]),
        ]

    def __str__(self):
        return f"Счёт №{self.pk} — {self.patient} ({self.get_status_display()})"

    def clean(self):
        if self.pk:
            original_status = (
                Invoice.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if original_status in TERMINAL_STATUSES and original_status != self.status:
                raise ValidationError(
                    "Счёт уже отменён (%s) — статус больше нельзя менять."
                    % InvoiceStatus(original_status).label
                )

    @property
    def total_amount(self) -> Decimal:
        agg = self.lines.aggregate(
            total=Coalesce(Sum(models.F("quantity") * models.F("unit_price")), ZERO)
        )
        return agg["total"]

    @property
    def paid_total(self) -> Decimal:
        paid = self.payments.filter(kind=PaymentKind.PAYMENT).aggregate(
            s=Coalesce(Sum("amount"), ZERO)
        )["s"]
        refunded = self.payments.filter(kind=PaymentKind.REFUND).aggregate(
            s=Coalesce(Sum("amount"), ZERO)
        )["s"]
        return paid - refunded

    @property
    def balance_due(self) -> Decimal:
        return self.total_amount - self.paid_total

    @property
    def is_paid(self) -> bool:
        return self.status == InvoiceStatus.ISSUED and self.balance_due <= ZERO

    def issue(self) -> bool:
        """DRAFT -> ISSUED. Returns False (no-op) if not currently DRAFT —
        same no-op-safe shape as Referral.mark_completed/LabOrder.cancel.
        full_clean() before save (even though the state check above
        already guards this specific path) so the terminal-status guard
        in clean() stays real defense-in-depth against any other code
        path that sets .status directly — same belt-and-suspenders style
        already used in Referral's schedule/decline actions."""
        if self.status != InvoiceStatus.DRAFT:
            return False
        if not self.lines.exists():
            raise ValidationError("В счёте нет ни одной позиции — нечего выставлять.")
        self.status = InvoiceStatus.ISSUED
        self.full_clean()
        self.save(update_fields=["status", "updated_at"])
        return True

    def cancel(self) -> bool:
        """DRAFT/ISSUED -> CANCELLED. Returns False if already terminal.
        Refuses (raises) to cancel an invoice with real money against it —
        a cashier has to refund first, so the payment ledger always
        explains where the money went instead of a cancelled invoice
        quietly writing off a paid balance."""
        if self.status in TERMINAL_STATUSES:
            return False
        if self.paid_total > ZERO:
            raise ValidationError(
                "По счёту уже есть платежи — сначала оформите возврат, потом отмените счёт."
            )
        self.status = InvoiceStatus.CANCELLED
        self.full_clean()
        self.save(update_fields=["status", "updated_at"])
        return True


class InvoiceLine(models.Model):
    """One billed item — free-text description for now (same choice
    already made for Visit.reason/LabOrder.test_type before a dedicated
    catalog exists). Phase 3 step (b) adds an optional `service` FK once
    Service/Price exists, without removing description/unit_price — those
    stay the snapshot of what was actually charged at billing time, immune
    to a later price change in the catalog (same "snapshot, not live
    link" principle as Referral.diagnosis_snapshot).
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.description} x{self.quantity}"

    @property
    def line_total(self) -> Decimal:
        return self.quantity * self.unit_price

    def clean(self):
        if self.invoice_id and self.invoice.status != InvoiceStatus.DRAFT:
            raise ValidationError(
                "Позиции счёта можно менять только пока счёт в статусе «Черновик»."
            )


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Наличные"
    CARD = "card", "Карта"
    OTHER = "other", "Другое"


class PaymentKind(models.TextChoices):
    PAYMENT = "payment", "Оплата"
    REFUND = "refund", "Возврат"


class Payment(models.Model):
    """One entry in the append-only payment ledger for an Invoice —
    created and never edited or deleted (PaymentViewSet is
    list/retrieve-only, see views.py). A correction is a new REFUND row,
    not an edit of history: this is the "event-sourcing lite" the phase
    was scoped around — "почему касса не сходится" has to be answerable
    from Payment.objects.filter(...) after the fact, not from a running
    balance nobody can audit.

    `branch` is denormalized from invoice.branch (not just joined
    through) so a payment's own branch is a fact recorded in place, and
    the network report can aggregate Payment directly without joining
    Invoice for every row.
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="payments"
    )
    received_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="payments_received"
    )
    kind = models.CharField(max_length=20, choices=PaymentKind.choices, default=PaymentKind.PAYMENT)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    # Always positive — `kind` carries the direction, so a refund is a
    # PaymentKind.REFUND row with a positive amount, not a negative number
    # that would silently net out in a naive SUM("amount").
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["branch", "received_at"]),
            models.Index(fields=["invoice"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} — счёт №{self.invoice_id}"

    def clean(self):
        if self.amount is not None and self.amount <= ZERO:
            raise ValidationError({"amount": "Сумма должна быть положительной."})
