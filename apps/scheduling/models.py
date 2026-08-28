from django.core.exceptions import ValidationError
from django.db import models


class AppointmentStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Запланирован"
    CONFIRMED = "confirmed", "Подтверждён"
    IN_PROGRESS = "in_progress", "Идёт приём"
    COMPLETED = "completed", "Завершён"
    CANCELLED = "cancelled", "Отменён"
    NO_SHOW = "no_show", "Неявка"


ACTIVE_STATUSES = (
    AppointmentStatus.SCHEDULED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
)


class Appointment(models.Model):
    """A booked slot for one doctor, at one branch, for one patient.

    Every appointment belongs to exactly one Branch — this is the field
    that lets the schedule UI filter by branch, and that RBAC v2 uses to
    decide who can see/manage it (see apps.accounts.rbac).
    """

    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="appointments"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="appointments"
    )
    doctor = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="appointments"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=AppointmentStatus.choices, default=AppointmentStatus.SCHEDULED
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["branch", "doctor", "starts_at"]),
            models.Index(fields=["branch", "starts_at"]),
        ]

    def __str__(self):
        return f"{self.patient} -> {self.doctor} @ {self.branch} ({self.starts_at:%Y-%m-%d %H:%M})"

    def clean(self):
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError("Начало приёма должно быть раньше окончания.")

        if self.doctor_id and self.starts_at and self.ends_at:
            # Doctors can be scheduled at different branches on different
            # days/hours (see apps.branches.StaffBranchAssignment), but
            # can't physically be in two places at once — so this check is
            # intentionally NOT scoped to self.branch_id.
            overlapping = (
                Appointment.objects.filter(
                    doctor_id=self.doctor_id,
                    status__in=ACTIVE_STATUSES,
                    starts_at__lt=self.ends_at,
                    ends_at__gt=self.starts_at,
                )
                .exclude(pk=self.pk)
                .exists()
            )
            if overlapping:
                raise ValidationError(
                    "У врача уже есть приём, пересекающийся по времени (в этом или другом филиале)."
                )
