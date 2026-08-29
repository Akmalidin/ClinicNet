from django.contrib.auth.models import AbstractUser
from django.db import models


class Specialty(models.Model):
    """Medical specialty catalog (Phase 2: needed to route a Referral to
    "whoever does orthodontics" without the referring doctor having to
    pick a specific colleague — see apps.referrals.models.Referral.to_specialty
    and User.specialties below).
    """

    name = models.CharField(max_length=120, unique=True)
    code = models.SlugField(max_length=120, unique=True)

    class Meta:
        verbose_name_plural = "specialties"
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Staff member within a clinic network (tenant-scoped).

    Patients are NOT users in Phase 1 — they are modelled separately in
    apps.patients. This model is for doctors, admins, receptionists, etc.
    """

    phone = models.CharField(max_length=32, blank=True)
    job_title = models.CharField(
        max_length=120,
        blank=True,
        help_text="Например: врач-стоматолог, администратор, кассир.",
    )
    specialties = models.ManyToManyField(
        Specialty,
        blank=True,
        related_name="doctors",
        help_text="Специальности врача — по ним подбираются кандидаты для направления "
        "'на специальность' (Referral.to_specialty), без выбора конкретного коллеги.",
    )

    def __str__(self):
        return self.get_full_name() or self.username


class Role(models.Model):
    """A named collection of permissions, e.g. 'Врач', 'Администратор сети'."""

    name = models.CharField(max_length=120, unique=True)
    codename = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(
        default=False,
        help_text="Системные роли нельзя удалить из UI (напр. Owner, Admin).",
    )
    permissions = models.ManyToManyField(
        "Permission", through="RolePermission", related_name="roles", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Permission(models.Model):
    """Catalog of fine-grained permission codes, e.g. 'appointment.create'."""

    code = models.CharField(max_length=150, unique=True)
    category = models.CharField(
        max_length=60,
        blank=True,
        help_text="Группировка в UI, напр. 'scheduling', 'billing'.",
    )
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["category", "code"]

    def __str__(self):
        return self.code


class RolePermission(models.Model):
    """Which permissions a role grants (catalog-level, not branch-scoped)."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("role", "permission")

    def __str__(self):
        return f"{self.role} -> {self.permission}"


class BranchScope(models.TextChoices):
    """How far a granted role reaches across the network's branches."""

    ALL = "all", "Все филиалы"
    OWN_BRANCH = "own_branch", "Только свои филиалы (по расписанию)"
    SPECIFIC_BRANCHES = "specific_branches", "Выбранные филиалы"


class UserRole(models.Model):
    """A role granted to a user, scoped to one/some/all branches.

    This is where RBAC v2's branch awareness actually lives: the same
    Role (e.g. "Врач") can be granted to one user for all branches and to
    another user only for the branch(es) they work at.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_roles")
    branch_scope = models.CharField(
        max_length=20, choices=BranchScope.choices, default=BranchScope.OWN_BRANCH
    )
    branches = models.ManyToManyField(
        "branches.Branch",
        blank=True,
        related_name="scoped_user_roles",
        help_text="Заполняется только при branch_scope = specific_branches.",
    )
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "role")

    def __str__(self):
        return f"{self.user} :: {self.role} ({self.get_branch_scope_display()})"
