from django.db import models


class Patient(models.Model):
    """Minimal patient record, network-wide (not tied to a single branch).

    Phase 1 only needs enough of a Patient to hang an Appointment off of.
    The full EMR (medical history, referrals, etc.) is Phase 2 scope.
    """

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    primary_branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="primary_patients",
        help_text="Филиал, где пациент чаще всего наблюдается (справочно).",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.last_name} {self.first_name}".strip()
