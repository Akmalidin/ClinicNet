from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce

ZERO = Decimal("0")


class Product(models.Model):
    """Network-wide consumables/materials catalog — Phase 3 step (d):
    "складской учёт по филиалам" (master plan). Same network-wide-catalog
    shape as apps.finance.Service (step b): the PRODUCT is the same
    everywhere ("Анестетик Ultracain"), only its on-hand quantity and
    reorder threshold are per-branch (see Stock).
    """

    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=100, unique=True)
    unit = models.CharField(max_length=20, help_text="Единица учёта, например: шт, мл, уп.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.unit})"


class Stock(models.Model):
    """One branch's tracking of one product — whether they carry it at
    all, and the reorder threshold ("минимальные остатки") that triggers
    a low-stock alert. The on-hand quantity is deliberately NOT stored
    here — see on_hand_quantity, which sums StockMovement for this
    (product, branch) pair every time. Same "always computed, never a
    drifting cache" principle already applied throughout apps.finance:
    "почему на складе не сходится" has to be answerable from the movement
    history, not a running number nobody can audit.
    """

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="branch_stocks")
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="stocks")
    min_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=ZERO,
        help_text="Порог алерта «остаток ниже минимума» — 0 значит алерт не нужен.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "branch"], name="one_stock_row_per_product_branch"),
        ]
        indexes = [models.Index(fields=["branch"])]

    def __str__(self):
        return f"{self.product} @ {self.branch}"

    def clean(self):
        if self.min_quantity is not None and self.min_quantity < ZERO:
            raise ValidationError({"min_quantity": "Порог не может быть отрицательным."})

    @property
    def on_hand_quantity(self) -> Decimal:
        agg = StockMovement.objects.filter(product=self.product, branch=self.branch).aggregate(
            s=Coalesce(Sum("quantity_delta"), ZERO)
        )
        return agg["s"]

    @property
    def is_below_minimum(self) -> bool:
        return self.min_quantity > ZERO and self.on_hand_quantity < self.min_quantity


class StockMovementReason(models.TextChoices):
    RESTOCK = "restock", "Поступление"
    CONSUMPTION = "consumption", "Списание"
    ADJUSTMENT = "adjustment", "Корректировка"


class StockMovement(models.Model):
    """One append-only entry in the stock ledger — created, never edited
    or deleted (StockMovementViewSet is list/retrieve-only, same shape as
    apps.finance.Payment; see that model's docstring for the reasoning).
    quantity_delta is positive for a restock, negative for consumption or
    a downward adjustment — direction lives in the sign here (unlike
    Payment.amount, which is always positive with `kind` carrying
    direction) because a stock ledger genuinely has no natural "kind vs.
    amount" split the way money does: a restock and a consumption are
    both just "how much moved," and summing quantity_delta directly is
    the on-hand quantity, with no separate subtraction step needed.
    """

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="stock_movements")
    quantity_delta = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=20, choices=StockMovementReason.choices)
    source_visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
        help_text="Приём, при закрытии которого произошло списание — необязателен.",
    )
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="stock_movements_made"
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "branch", "-created_at"]),
            models.Index(fields=["branch", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_reason_display()} {self.quantity_delta} {self.product} @ {self.branch}"

    def clean(self):
        if self.quantity_delta == ZERO:
            raise ValidationError({"quantity_delta": "Движение не может быть нулевым."})
