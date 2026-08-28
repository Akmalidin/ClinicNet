from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ReferralStatus(models.TextChoices):
    PENDING = "pending", "Ожидает"  # создано, слот ещё не выбран/не подтверждён
    SCHEDULED = "scheduled", "Запланировано"  # подтверждён слот у принимающего врача
    ACCEPTED = "accepted", "Принято"  # пациент пришёл, приём начат
    COMPLETED = "completed", "Завершено"  # приём у принимающего врача закрыт
    DECLINED = "declined", "Отклонено"  # принимающий врач/координатор отклонил
    CANCELLED = "cancelled", "Отменено"  # отменено направившим врачом или пациентом


class ReferralPriority(models.TextChoices):
    ROUTINE = "routine", "Плановое"
    URGENT = "urgent", "Срочное"
    EMERGENCY = "emergency", "Экстренное"


class Referral(models.Model):
    """A bridge between two doctors (same branch or across branches),
    carrying visit context, tracked through to close.

    See docs/PHASE2-REFERRALS-DESIGN.md for how this maps onto
    ClinicNet-Referrals-Prompt.md and where it diverges (source_visit points
    at apps.visits.Visit — new in this phase — not scheduling.Appointment;
    to_specialty points at the new accounts.Specialty catalog; RBAC uses the
    project's own branch-scoped permission system, not Django's has_perm()).
    """

    # Кто и куда
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="referrals"
    )
    from_doctor = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="referrals_sent"
    )
    to_doctor = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="referrals_received",
        null=True,
        blank=True,  # null = направлено "на специальность", конкретный врач не выбран
    )
    to_specialty = models.ForeignKey(
        "accounts.Specialty", on_delete=models.PROTECT, null=True, blank=True,
        related_name="referrals",
    )

    from_branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="referrals_out"
    )
    to_branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="referrals_in"
    )

    # Контекст визита (снапшот на момент направления — не ссылка "вживую",
    # чтобы принимающий врач видел карту такой, какой она была при направлении)
    source_visit = models.ForeignKey(
        "visits.Visit", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="referrals",
    )
    reason = models.CharField(max_length=255)  # "Ортодонтическая консультация"
    clinical_note = models.TextField(blank=True)  # жалобы/осмотр/диагноз на момент направления
    diagnosis_snapshot = models.JSONField(default=dict, blank=True)  # снимок с source_visit

    # Связка с реальной записью, когда слот выбран
    target_appointment = models.OneToOneField(
        "scheduling.Appointment", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="referral",
    )

    status = models.CharField(
        max_length=20, choices=ReferralStatus.choices, default=ReferralStatus.PENDING
    )
    priority = models.CharField(
        max_length=20, choices=ReferralPriority.choices, default=ReferralPriority.ROUTINE
    )

    # Обратная связь принимающего врача направившему
    outcome_note = models.TextField(blank=True)
    outcome_visible_to = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", help_text="Обычно = from_doctor, но можно переопределить",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "to_branch"]),
            models.Index(fields=["to_doctor", "status"]),
            models.Index(fields=["patient"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        to = self.to_doctor or self.to_specialty or "?"
        return f"{self.patient} → {to} ({self.get_status_display()})"

    def clean(self):
        if not self.to_doctor_id and not self.to_specialty_id:
            raise ValidationError("Укажите принимающего врача или специальность.")
        if self.status == ReferralStatus.DECLINED and not self.outcome_note:
            raise ValidationError(
                {"outcome_note": "При отклонении направления причина обязательна."}
            )

    def mark_completed(self, outcome_note: str = ""):
        self.status = ReferralStatus.COMPLETED
        self.completed_at = timezone.now()
        if outcome_note:
            self.outcome_note = outcome_note
        self.save(update_fields=["status", "completed_at", "outcome_note", "updated_at"])
