from django.core.exceptions import ValidationError
from django.db import models


class LabOrderStatus(models.TextChoices):
    ORDERED = "ordered", "Заказан"
    COMPLETED = "completed", "Есть результат"
    CANCELLED = "cancelled", "Отменён"


class LabOrderUrgency(models.TextChoices):
    ROUTINE = "routine", "Плановое"
    URGENT = "urgent", "Срочное"
    EMERGENCY = "emergency", "Экстренное"


# Same terminal-state pattern as apps.referrals.models.TERMINAL_STATUSES —
# a closed order (result entered, or cancelled) doesn't change status again.
TERMINAL_STATUSES = (LabOrderStatus.COMPLETED, LabOrderStatus.CANCELLED)


class LabOrder(models.Model):
    """A lab/diagnostic test ordered from a patient's card — Phase 2's
    "базовая диагностика" (ClinicNet-Phase2-Frontend-Prompt.md): deliberately
    simple, no lab-analyzer integration and no test catalog, matching the
    same free-text choice already made for Visit.reason/Referral.reason in
    this project rather than inventing a reference catalog this phase
    doesn't need.
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="lab_orders"
    )
    ordered_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="lab_orders_placed"
    )
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="lab_orders"
    )
    source_visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_orders",
        help_text="Осмотр, из карты которого заказан анализ — необязателен "
        "(можно заказать и вне текущего приёма).",
    )
    test_type = models.CharField(max_length=200, verbose_name="Тип анализа")
    comment = models.TextField(blank=True, verbose_name="Комментарий")
    urgency = models.CharField(
        max_length=20, choices=LabOrderUrgency.choices, default=LabOrderUrgency.ROUTINE
    )
    status = models.CharField(
        max_length=20, choices=LabOrderStatus.choices, default=LabOrderStatus.ORDERED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "-created_at"]),
            models.Index(fields=["branch", "status"]),
        ]

    def __str__(self):
        return f"{self.patient} — {self.test_type} ({self.get_status_display()})"

    def clean(self):
        if self.pk:
            original_status = (
                LabOrder.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if original_status in TERMINAL_STATUSES and original_status != self.status:
                raise ValidationError(
                    "Заказ уже закрыт (%s) — статус больше нельзя менять."
                    % LabOrderStatus(original_status).label
                )

    def cancel(self) -> bool:
        """Returns False (no-op) if already terminal — same shape as
        apps.referrals.models.Referral.mark_completed, so the view action
        can tell a no-op from an error without an exception."""
        if self.status in TERMINAL_STATUSES:
            return False
        self.status = LabOrderStatus.CANCELLED
        self.save(update_fields=["status", "updated_at"])
        return True


class LabResult(models.Model):
    """The manually-entered result for a LabOrder — one per order
    (OneToOne), entered by "ответственный сотрудник" (spec wording):
    not necessarily the doctor who placed the order, could be whoever
    actually ran/received the test.

    is_abnormal is deliberately a plain boolean flag, not a structured
    reference-range/CDSS — exactly what the spec asks for ("простой
    булев флаг/диапазон, не полноценный CDSS").
    """

    order = models.OneToOneField(LabOrder, on_delete=models.CASCADE, related_name="result")
    entered_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="lab_results_entered"
    )
    result_text = models.TextField(verbose_name="Результат")
    is_abnormal = models.BooleanField(default=False, verbose_name="Результат вне нормы")
    entered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Результат: {self.order}"
