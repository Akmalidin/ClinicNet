from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Department(models.Model):
    """Отделение внутри филиала — Фаза 4: "Branch → Department → Room →
    Bed". В отличие от apps.finance.Service/apps.inventory.Product
    (сетевые каталоги — одна запись на всю сеть, филиал только
    переопределяет цену/остаток), Department — операционная единица
    КОНКРЕТНОГО филиала: "Терапевтическое отделение" в филиале А и
    "Терапевтическое отделение" в филиале Б — две разные записи, а не
    одна сетевая с филиальным оверрайдом — общей "сетевой" части тут
    просто нет.
    """

    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="departments"
    )
    name = models.CharField(max_length=150)
    code = models.SlugField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["branch_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "code"], name="unique_department_code_per_branch"),
        ]

    def __str__(self):
        return f"{self.name} ({self.branch})"


class Room(models.Model):
    """Палата внутри отделения — группировка коек (Bed) для отображения
    занятости на плане отделения."""

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="rooms")
    name = models.CharField(max_length=50, help_text="Номер/название палаты, напр. «204».")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["department_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["department", "name"], name="unique_room_name_per_department"),
        ]

    def __str__(self):
        return f"{self.name} ({self.department})"

    @property
    def branch(self):
        """For HasBranchPermission's generic `getattr(obj, "branch", None)`
        object-level resolution — Room isn't itself branch-scoped by an FK,
        but structurally managing ward layout is a branch-admin action,
        same tier as apps.branches management, so it reuses the existing
        branch permission machinery rather than the new department-scoped
        one (that one is for PATIENT DATA — Admission/ClinicalOrder/
        VitalsRecord — not for editing the ward structure itself)."""
        return self.department.branch


class BedStatus(models.TextChoices):
    FREE = "free", "Свободна"
    OCCUPIED = "occupied", "Занята"
    CLEANING = "cleaning", "Уборка"
    RESERVED = "reserved", "Резерв"


class Bed(models.Model):
    """Одна койка. `status` — единственный источник правды о занятости,
    но OCCUPIED — производное состояние: оно выставляется/снимается
    только как побочный эффект Admission (см. apps.inpatient.services.
    admit_patient/discharge_admission), а не напрямую через API — это
    гарантирует, что "занята" всегда значит "есть активная
    госпитализация на эту койку", а не рассинхронизированный флаг
    (тот же принцип единственного источника правды, что у
    Stock.on_hand_quantity, просто здесь состояние — не число, поэтому
    не может быть чисто вычисляемым: FREE/CLEANING/RESERVED — это
    операционные пометки персонала, которые ни из чего не выводятся).
    Управление статусом идёт через BedViewSet.set_status (action, не
    сырой PATCH) — тот же паттерн, что Invoice/LabOrder/Referral.
    """

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="beds")
    label = models.CharField(max_length=20, help_text="Номер койки внутри палаты, напр. «1».")
    status = models.CharField(max_length=20, choices=BedStatus.choices, default=BedStatus.FREE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["room_id", "label"]
        constraints = [
            models.UniqueConstraint(fields=["room", "label"], name="unique_bed_label_per_room"),
        ]

    def __str__(self):
        return f"{self.room} / {self.label} ({self.get_status_display()})"

    @property
    def department(self):
        return self.room.department

    @property
    def branch(self):
        return self.room.department.branch


class StaffDepartmentAssignment(models.Model):
    """Отделения, к которым приписан сотрудник (постовая медсестра,
    зав. отделением, лечащий врач) — тот же принцип, что
    apps.branches.StaffBranchAssignment, но на уровень RBAC глубже и
    НЕ часть apps.accounts.rbac: отдельная, локальная для стационара
    таблица, чтобы не трогать фундамент, на котором работают все
    остальные фазы (решение зафиксировано явно при старте Фазы 4).
    См. apps.inpatient.rbac.departments_for_permission — вот где это
    реально используется для ограничения видимости.
    """

    staff = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="department_assignments"
    )
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="staff_assignments")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["staff", "department"], name="unique_staff_department"),
        ]

    def __str__(self):
        return f"{self.staff} @ {self.department}"


class AdmissionStatus(models.TextChoices):
    ACTIVE = "active", "Активна"
    DISCHARGED = "discharged", "Выписан"


# Один терминальный статус, не три, как в черновике промпта (active/
# transferred/discharged) — "переведён" не тupik, госпитализация после
# перевода остаётся активной, просто в другом отделении/на другой
# койке; сам факт перевода — запись в Transfer (append-only лог, шаг c),
# а не отдельное состояние Admission, иначе неясно, что происходит
# ПОСЛЕ "transferred" и как из него попасть обратно в "active".
TERMINAL_STATUSES = (AdmissionStatus.DISCHARGED,)


class Admission(models.Model):
    """Госпитализация — отдельная сущность с собственным жизненным
    циклом, НЕ Visit с длинным сроком (разведка Фазы 4: перевод между
    отделениями, лист наблюдения и выписка с эпикризом не укладываются
    в модель одного амбулаторного приёма).

    department/bed отражают ТЕКУЩЕЕ местоположение пациента — история
    переводов не здесь, а в Transfer (append-only, шаг c, тот же
    принцип, что Payment/StockMovement): смена department/bed напрямую
    через PATCH теряла бы историю, нужную для эпикриза, поэтому в API
    это action (apps.inpatient.services), не сырой PATCH.
    """

    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="admissions")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="admissions")
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="admissions")
    attending_doctor = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="admissions_attending"
    )
    admitted_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="admissions_placed"
    )
    diagnosis_at_admission = models.TextField(verbose_name="Диагноз при поступлении")
    status = models.CharField(
        max_length=20, choices=AdmissionStatus.choices, default=AdmissionStatus.ACTIVE
    )
    admitted_at = models.DateTimeField(default=timezone.now)
    discharged_at = models.DateTimeField(null=True, blank=True)
    discharge_epicrisis = models.TextField(blank=True, verbose_name="Выписной эпикриз")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-admitted_at"]
        indexes = [
            models.Index(fields=["department", "status"]),
            models.Index(fields=["patient", "-admitted_at"]),
            models.Index(fields=["bed", "status"]),
        ]

    def __str__(self):
        return f"{self.patient} — {self.department} / {self.bed} ({self.get_status_display()})"

    @property
    def branch(self):
        return self.department.branch

    def clean(self):
        if self.pk:
            original_status = (
                Admission.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if original_status in TERMINAL_STATUSES and original_status != self.status:
                raise ValidationError(
                    "Госпитализация уже завершена (%s) — статус больше нельзя менять."
                    % AdmissionStatus(original_status).label
                )
        if self.bed_id and self.department_id and self.bed.room.department_id != self.department_id:
            raise ValidationError({"bed": "Койка не принадлежит указанному отделению."})
        if self.status == AdmissionStatus.ACTIVE and self.bed_id:
            # Одна койка — максимум одна активная госпитализация
            # одновременно (тот же приём, что Appointment.clean()'s
            # overlap-check, только вместо пересечения по времени —
            # простое "уже занято", т.к. койка не бронируется на
            # интервалы, а держится одной госпитализацией до выписки/
            # перевода).
            clash = (
                Admission.objects.filter(bed_id=self.bed_id, status=AdmissionStatus.ACTIVE)
                .exclude(pk=self.pk)
                .exists()
            )
            if clash:
                raise ValidationError({"bed": "Эта койка уже занята другой активной госпитализацией."})

    def discharge(self, epicrisis: str = "") -> bool:
        """IN_PROGRESS(active) -> DISCHARGED. Returns False (no-op) if
        already terminal — same no-op-safe shape as Visit.close/
        Referral.mark_completed/LabOrder.cancel, so a retried request
        can't silently double-process a discharge. Freeing the bed is a
        side effect handled by apps.inpatient.services.discharge_admission,
        which calls this — not here, to keep model methods free of
        cross-model side effects the way Visit.close() does (stock
        deduction also lives in a services module, not on the model)."""
        if self.status in TERMINAL_STATUSES:
            return False
        self.status = AdmissionStatus.DISCHARGED
        self.discharged_at = timezone.now()
        if epicrisis:
            self.discharge_epicrisis = epicrisis
        self.full_clean()
        self.save(update_fields=["status", "discharged_at", "discharge_epicrisis", "updated_at"])
        return True
