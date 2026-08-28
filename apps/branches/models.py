from django.core.exceptions import ValidationError
from django.db import models


class BranchStatus(models.TextChoices):
    ACTIVE = "active", "Работает"
    OPENING = "opening", "Открывается"
    CLOSED = "closed", "Закрыт"


class Branch(models.Model):
    """A physical clinic location within a network (tenant)."""

    name = models.CharField(max_length=150)
    code = models.SlugField(max_length=50, unique=True)
    address = models.CharField(max_length=255, blank=True)
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        help_text="IANA timezone, напр. Asia/Bishkek.",
    )
    status = models.CharField(
        max_length=10, choices=BranchStatus.choices, default=BranchStatus.ACTIVE
    )
    phone = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.status == BranchStatus.ACTIVE


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Понедельник"
    TUESDAY = 1, "Вторник"
    WEDNESDAY = 2, "Среда"
    THURSDAY = 3, "Четверг"
    FRIDAY = 4, "Пятница"
    SATURDAY = 5, "Суббота"
    SUNDAY = 6, "Воскресенье"


class StaffBranchAssignment(models.Model):
    """Which branch(es) a staff member works at, and on what schedule.

    This drives BranchScope.OWN_BRANCH in RBAC v2 (apps.accounts.rbac):
    a role granted with own_branch scope reaches exactly the branches a
    user has an active assignment to here, regardless of the weekday rows.
    """

    staff = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="branch_assignments"
    )
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="staff_assignments")
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["staff_id", "weekday", "start_time"]
        indexes = [models.Index(fields=["staff", "branch", "is_active"])]

    def __str__(self):
        return f"{self.staff} @ {self.branch} ({self.get_weekday_display()} {self.start_time}-{self.end_time})"

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError("Время начала смены должно быть раньше времени окончания.")
