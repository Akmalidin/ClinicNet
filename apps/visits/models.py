from django.db import models
from django.utils import timezone


class VisitStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "Идёт приём"
    COMPLETED = "completed", "Завершён"
    CANCELLED = "cancelled", "Отменён"


class Visit(models.Model):
    """A clinical encounter: what the master plan calls "Visit" — the
    doctor's notes/diagnosis for one meeting with a patient, as opposed to
    `scheduling.Appointment`, which is just the calendar slot.

    Phase 2 introduces this specifically so Referral has a real clinical
    context to snapshot from (see apps.referrals.models.Referral.source_visit)
    and so the "единая ЭМК" goal has an actual clinical-content layer, not
    just demographics (Patient) and a calendar (Appointment).
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="visits"
    )
    doctor = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="visits"
    )
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="visits"
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
        help_text="Календарная запись, из которой возник приём. Пусто — визит "
        "без предварительной записи (walk-in).",
    )
    reason = models.CharField(max_length=255, blank=True, verbose_name="Повод обращения")
    clinical_note = models.TextField(blank=True, verbose_name="Клиническая заметка")
    diagnosis_snapshot = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Диагноз (снимок)",
        help_text="Свободная структура — в проекте пока нет отдельной модели одонтограммы/"
        "диагноза, которую можно было бы снимать; формируется позже, когда появится.",
    )
    status = models.CharField(
        max_length=20, choices=VisitStatus.choices, default=VisitStatus.IN_PROGRESS
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "-created_at"]),
            models.Index(fields=["branch", "doctor"]),
        ]

    def __str__(self):
        return f"{self.patient} — {self.doctor} ({self.get_status_display()})"

    def close(self) -> bool:
        """IN_PROGRESS -> COMPLETED. Returns False (no-op) if already
        closed — same no-op-safe shape as Referral.mark_completed/
        LabOrder.cancel, so a second close() (e.g. a retried request)
        can't silently overwrite the original closed_at. Previously this
        method existed but nothing in the API ever called it (found
        during Phase 3 recon: VisitViewSet had no close/complete action
        at all, just a raw PATCH on `status` with no state-transition
        guard) — apps.inventory's stock deduction is wired to the real
        action that now calls this (apps.visits.views.VisitViewSet.close).
        """
        if self.status != VisitStatus.IN_PROGRESS:
            return False
        self.status = VisitStatus.COMPLETED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])
        return True
