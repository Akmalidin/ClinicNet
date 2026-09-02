from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"  # line items still editable, no payments yet
    ISSUED = "issued", "Выставлен"  # locked, ready to accept payments
    CANCELLED = "cancelled", "Отменён"


# Same terminal-state pattern as apps.referrals/apps.diagnostics — a
# cancelled invoice's status can't change again.
TERMINAL_STATUSES = (InvoiceStatus.CANCELLED,)

ZERO = Decimal("0")


class Service(models.Model):
    """The network-wide price catalog — Phase 3 step (b): "единый прайс с
    возможностью филиал-специфичных цен" (master plan). `base_price` is
    the network default; a branch that needs a different price for this
    service gets a `BranchPriceOverride` row instead of a whole separate
    catalog — no duplicating the price list per branch.

    Deliberately network-wide (no `branch` field): a service like
    "Консультация" is the same *service* everywhere, only its price can
    differ per branch. Managing this catalog (create/edit/deactivate a
    service, or change its base_price) is a network-wide action —
    requires an ALL-scope grant of pricing.manage (see
    apps.accounts.permissions.HasNetworkWidePermission) — while setting a
    branch's override is a branch-scoped action any branch-admin can do
    for their own branch (pricing.override, via HasBranchPermission on
    BranchPriceOverride).
    """

    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=100, unique=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.base_price is not None and self.base_price < ZERO:
            raise ValidationError({"base_price": "Цена не может быть отрицательной."})

    def price_for(self, branch) -> Decimal:
        """The effective price at `branch` — its override if one exists,
        otherwise the network base_price. This is what add_line resolves
        at billing time and snapshots onto InvoiceLine.unit_price; a later
        change here or to the override never touches an already-billed
        line (see InvoiceLine's docstring)."""
        override = self.branch_overrides.filter(branch=branch).first()
        return override.price if override else self.base_price


class BranchPriceOverride(models.Model):
    """One branch's exception to a Service's network base_price — not a
    duplicate price list, just the deltas. Absence of a row for a given
    (service, branch) pair means "use the network price", not "no price
    set" — Service.price_for() falls back to base_price automatically.
    """

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="branch_overrides")
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.CASCADE, related_name="service_price_overrides"
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["service", "branch"], name="one_override_per_service_branch"),
        ]

    def __str__(self):
        return f"{self.service} @ {self.branch}: {self.price}"

    def clean(self):
        if self.price is not None and self.price < ZERO:
            raise ValidationError({"price": "Цена не может быть отрицательной."})


class InsuranceProvider(models.Model):
    """Catalog of insurance companies — Phase 3 step (c): "лимиты по
    полису, разделение чека пациент/страховая", explicitly internal logic
    only (no external API to verify a policy or submit a claim, confirmed
    before building this). A lightweight network-wide catalog, same shape
    as Service — no external integration means no need to store anything
    beyond a name/code to reference.
    """

    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class InsurancePolicy(models.Model):
    """One patient's policy with one provider. `coverage_percent` (what
    fraction of a bill the insurer pays) and `coverage_limit` (the total
    the policy will ever pay out, across every invoice against it) are
    exactly the "лимиты по полису" the phase asked for — deliberately
    simple compared to a real insurer's rules (no per-service exclusions,
    no annual reset), matching the same "не полноценный CDSS"-style scope
    limit already applied to LabResult.is_abnormal.

    Policies are patient data, not branch data (same reasoning as Patient
    itself being network-wide) — a patient's policy applies at whichever
    branch they're billed at.
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="insurance_policies"
    )
    provider = models.ForeignKey(InsuranceProvider, on_delete=models.PROTECT, related_name="policies")
    policy_number = models.CharField(max_length=100)
    coverage_percent = models.PositiveSmallIntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Какую долю каждого счёта покрывает страховая (0-100%).",
    )
    coverage_limit = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Общий лимит покрытия по полису — сумма всех счетов, оплаченных страховой, не может его превысить.",
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient"])]

    def __str__(self):
        return f"{self.provider} №{self.policy_number} — {self.patient}"

    def clean(self):
        if self.coverage_limit is not None and self.coverage_limit < ZERO:
            raise ValidationError({"coverage_limit": "Лимит не может быть отрицательным."})
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValidationError({"valid_until": "Дата окончания раньше даты начала."})

    def is_valid_on(self, date) -> bool:
        if not self.is_active:
            return False
        if self.valid_from and date < self.valid_from:
            return False
        if self.valid_until and date > self.valid_until:
            return False
        return True

    @property
    def used_amount(self) -> Decimal:
        """Sum of insurance_covered_amount across every non-draft,
        non-cancelled invoice already billed against this policy — a
        cancelled invoice's coverage is excluded, so cancelling one
        automatically frees that part of the limit back up for the next
        invoice, with no separate "release" step needed (see Invoice.cancel).
        """
        return self.invoices.exclude(
            status__in=(InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)
        ).aggregate(s=Coalesce(Sum("insurance_covered_amount"), ZERO))["s"]

    @property
    def remaining_limit(self) -> Decimal:
        return max(self.coverage_limit - self.used_amount, ZERO)


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

    insurance_covered_amount is the one exception to "always computed,
    never stored" (see InsurancePolicy.used_amount): a policy's remaining
    limit is shared across every invoice billed against it, so how much
    THIS invoice claims has to be decided and locked in at issue() time,
    using the state of every earlier invoice against that same policy —
    it genuinely can't be a live-recomputed property the way total_amount
    is, because it depends on other rows, not just this one's own lines.
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
    insurance_policy = models.ForeignKey(
        InsurancePolicy,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
        help_text="Полис, по которому разделяется чек — необязателен (обычная оплата, если не указан).",
    )
    insurance_covered_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
        help_text="Снимок доли счёта, покрытой страховой — считается один раз при issue(), см. докстринг класса.",
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
            original = (
                Invoice.objects.filter(pk=self.pk)
                .values("status", "insurance_policy_id")
                .first()
            )
            if original:
                if original["status"] in TERMINAL_STATUSES and original["status"] != self.status:
                    raise ValidationError(
                        "Счёт уже отменён (%s) — статус больше нельзя менять."
                        % InvoiceStatus(original["status"]).label
                    )
                if (
                    original["status"] != InvoiceStatus.DRAFT
                    and original["insurance_policy_id"] != self.insurance_policy_id
                ):
                    raise ValidationError(
                        "Полис нельзя менять после выставления счёта — "
                        "доля страховой уже зафиксирована."
                    )

    @property
    def total_amount(self) -> Decimal:
        agg = self.lines.aggregate(
            total=Coalesce(Sum(models.F("quantity") * models.F("unit_price")), ZERO)
        )
        return agg["total"]

    @property
    def patient_owed_amount(self) -> Decimal:
        """What the PATIENT owes at this register — total_amount minus
        whatever the policy covers (insurance_covered_amount, snapshotted
        at issue()). balance_due/is_paid track this, not total_amount:
        the insurer's share isn't collected through Payment/pay() at all
        in this phase (no external claims integration — see the model
        docstring), so counting it as "still due" here would make an
        invoice with insurance look permanently unpaid at the register."""
        return self.total_amount - self.insurance_covered_amount

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
        return self.patient_owed_amount - self.paid_total

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
        already used in Referral's schedule/decline actions.

        If insurance_policy is set, this is where insurance_covered_amount
        gets computed and locked in — capped by both the policy's
        coverage_percent and whatever's left of its coverage_limit at
        this exact moment (earlier invoices against the same policy have
        first claim; see InsurancePolicy.remaining_limit)."""
        if self.status != InvoiceStatus.DRAFT:
            return False
        if not self.lines.exists():
            raise ValidationError("В счёте нет ни одной позиции — нечего выставлять.")

        if self.insurance_policy_id:
            policy = self.insurance_policy
            if not policy.is_valid_on(timezone.now().date()):
                raise ValidationError(
                    {"insurance_policy": "Полис недействителен (неактивен или истёк срок)."}
                )
            by_percent = (self.total_amount * policy.coverage_percent) / Decimal("100")
            self.insurance_covered_amount = min(by_percent, policy.remaining_limit, self.total_amount)

        self.status = InvoiceStatus.ISSUED
        self.full_clean()
        self.save(update_fields=["status", "insurance_covered_amount", "updated_at"])
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
    """One billed item. `service` is optional — set when the line was
    added from the price catalog (InvoiceViewSet.add_line resolves
    Service.price_for(invoice.branch) and snapshots the result onto
    description/unit_price at that moment); null for an ad-hoc line typed
    in free-text, the same choice already made for Visit.reason/
    LabOrder.test_type before a catalog existed.

    description/unit_price are ALWAYS the snapshot of what was actually
    charged, service or not — a later change to Service.base_price or a
    BranchPriceOverride never touches an already-billed line (same
    "snapshot, not live link" principle as Referral.diagnosis_snapshot).
    `service` itself is kept only for reporting ("how much did
    Консультация bring in this month"), never re-read for the price.
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, null=True, blank=True, related_name="invoice_lines",
    )
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
    QR = "qr", "QR / Мобильный"
    # 1 бонусный балл = 1 денежная единица — самое простое сопоставление,
    # тот же принцип упрощения, что у InsurancePolicy (без исключений по
    # услугам, без годового сброса). Баланс живёт на Patient.loyalty_points
    # (apps.patients) и уменьшается только здесь, при успешном pay() —
    # единая точка списания, без отдельного leger'а начислений/списаний,
    # т.к. начисления пока нет вообще (баланс правится только вручную,
    # через admin, до появления реальной программы лояльности).
    BONUS = "bonus", "Бонусами"
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
