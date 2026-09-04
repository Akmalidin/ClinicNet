from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
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


class AdmissionReason(models.TextChoices):
    """Найдено при разведке admissionintake.html — "Основание" госпи-
    тализации нигде не хранилось (только диагноз). Чисто описательная
    категоризация, ни на что не влияющая структурно (в отличие от
    статуса) — как AppointmentReason'а тут нет, справочника заводить не
    нужно, три варианта фиксированы прямо в макете."""

    PLANNED = "planned", "Плановая операция"
    EMERGENCY = "emergency", "Экстренная госпитализация"
    TRANSFER = "transfer", "Перевод из другого отделения"


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
    reason = models.CharField(
        max_length=20, choices=AdmissionReason.choices, default=AdmissionReason.PLANNED,
        verbose_name="Основание госпитализации",
    )
    notes = models.TextField(
        blank=True, verbose_name="Заметки при поступлении",
        help_text="Аллергии, план на ближайшую операцию и т.п. — отдельно от клинического диагноза.",
    )
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


class Transfer(models.Model):
    """Перевод — append-only лог, тот же принцип, что Payment/
    StockMovement: Admission.department/bed отражают ТЕКУЩЕЕ
    местоположение и меняются на месте, но история "откуда куда и
    когда" не восстановима из одной только текущей пары department/bed
    — поэтому каждый перевод фиксируется отдельной неизменяемой
    записью (нужна для выписного эпикриза). Создаётся только как
    побочный эффект apps.inpatient.services.transfer_admission, никогда
    напрямую через API — TransferViewSet только для чтения.

    from_department/from_bed и to_department/to_bed — тоже перевод
    внутри одного отделения на другую койку (не только между
    отделениями): модель называется "перевод" в широком смысле
    "сменил местоположение", госпитализация-между-отделениями — частный
    случай, отдельной модели для внутриотделенческого переноса заводить
    не нужно.
    """

    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="transfers")
    from_department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="transfers_out")
    from_bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="transfers_out")
    to_department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="transfers_in")
    to_bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="transfers_in")
    reason = models.CharField(max_length=255, blank=True)
    transferred_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="transfers_made"
    )
    transferred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transferred_at"]
        indexes = [models.Index(fields=["admission", "-transferred_at"])]

    def __str__(self):
        return f"{self.admission} : {self.from_department} → {self.to_department}"

    @property
    def department(self):
        """For HasDepartmentPermission's generic object-level resolution
        — the destination is treated as "this row's department" (same
        idea as Bed.department: the row belongs to wherever the patient
        ended up), while list-level scoping (see AdmissionViewSet/
        TransferViewSet.get_queryset) also includes from_department, so
        a nurse who was in the FROM department still sees the historic
        record of a patient who left it."""
        return self.to_department


class ClinicalOrderType(models.TextChoices):
    MEDICATION = "medication", "Медикамент"
    PROCEDURE = "procedure", "Процедура"
    DIET = "diet", "Диета"


class ClinicalOrderStatus(models.TextChoices):
    ORDERED = "ordered", "Назначено"
    COMPLETED = "completed", "Выполнено"
    CANCELLED = "cancelled", "Отменено"


# Тот же паттерн, что apps.referrals.models.TERMINAL_STATUSES/
# apps.diagnostics.models.LabOrderStatus's TERMINAL_STATUSES.
CLINICAL_ORDER_TERMINAL_STATUSES = (ClinicalOrderStatus.COMPLETED, ClinicalOrderStatus.CANCELLED)


class ClinicalOrder(models.Model):
    """Назначение — медикамент/процедура/диета. Свободный текст в
    description (не отдельный каталог препаратов/процедур), тот же
    выбор, что уже сделан для Visit.reason/LabOrder.test_type в этом
    проекте — вводить справочник не нужно для той функциональности,
    которую просит фаза.

    Разделение назначил/выполнил — реальный рабочий процесс стационара:
    врач назначает (ordered_by, inpatient.order.manage), постовая
    медсестра выполняет (performed_by, inpatient.order.perform) — это
    ДВА разных права, не одно "manage" на всё (см. seed_rbac.py и
    ClinicalOrderViewSet.complete's required_permission override).
    """

    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="orders")
    order_type = models.CharField(max_length=20, choices=ClinicalOrderType.choices)
    description = models.CharField(max_length=255, verbose_name="Назначение")
    scheduled_for = models.DateTimeField(
        null=True, blank=True, help_text="Когда должно быть выполнено — необязательно."
    )
    ordered_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="clinical_orders_placed"
    )
    status = models.CharField(
        max_length=20, choices=ClinicalOrderStatus.choices, default=ClinicalOrderStatus.ORDERED
    )
    performed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        related_name="clinical_orders_performed",
    )
    performed_at = models.DateTimeField(null=True, blank=True)
    performed_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["admission", "status"])]

    def __str__(self):
        return f"{self.get_order_type_display()}: {self.description} ({self.get_status_display()})"

    @property
    def department(self):
        return self.admission.department

    def clean(self):
        if self.pk:
            original_status = (
                ClinicalOrder.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if original_status in CLINICAL_ORDER_TERMINAL_STATUSES and original_status != self.status:
                raise ValidationError(
                    "Назначение уже закрыто (%s) — статус больше нельзя менять."
                    % ClinicalOrderStatus(original_status).label
                )
        else:
            # Только на создание — новое назначение не заводится для уже
            # выписанного пациента. Выполнить/отменить уже существующее
            # назначение можно и после выписки (не блокируем задним числом).
            if self.admission_id and self.admission.status != AdmissionStatus.ACTIVE:
                raise ValidationError("Нельзя назначить новую позицию для завершённой госпитализации.")

    def complete(self, performed_by, note: str = "") -> bool:
        """ORDERED -> COMPLETED. No-op-safe (returns False on a retried
        request) — same "повторное выполнение уже выполненного назначения
        должно быть отклонено" requirement as LabOrder's result/ guard."""
        if self.status in CLINICAL_ORDER_TERMINAL_STATUSES:
            return False
        self.status = ClinicalOrderStatus.COMPLETED
        self.performed_by = performed_by
        self.performed_at = timezone.now()
        if note:
            self.performed_note = note
        self.full_clean()
        self.save(update_fields=["status", "performed_by", "performed_at", "performed_note", "updated_at"])
        return True

    def cancel(self) -> bool:
        if self.status in CLINICAL_ORDER_TERMINAL_STATUSES:
            return False
        self.status = ClinicalOrderStatus.CANCELLED
        self.save(update_fields=["status", "updated_at"])
        return True


class VitalsRecord(models.Model):
    """Лист наблюдения — append-only, тот же принцип, что Payment/
    StockMovement/Transfer: один замер — одна неизменяемая запись,
    ошибочный замер компенсируется НОВОЙ записью, а не правкой старой
    (та же логика, что делает возможным разобраться "почему касса не
    сходится" для денег — здесь "что реально показывал монитор в 09:00",
    не отредактированная задним числом история). "Текущие" показатели —
    последняя по recorded_at запись, не отдельно хранимое поле.

    Никакого update/delete в API вообще (VitalsRecordViewSet — только
    create/list/retrieve) — не "read-only после создания одним action'ом"
    как Payment/StockMovement/Transfer (у тех создание — побочный эффект
    другого действия), а "создаётся напрямую, но неизменяемо после" —
    ближайший в проекте аналог это LabResult (тоже вводится один раз и
    не редактируется), только без OneToOne-ограничения: замеров за
    госпитализацию много.
    """

    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="vitals_records")
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="vitals_records_made"
    )
    blood_pressure_systolic = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="АД систолическое"
    )
    blood_pressure_diastolic = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="АД диастолическое"
    )
    pulse = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Пульс")
    temperature = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, verbose_name="Температура"
    )
    # Найдено при разведке vitalschart.html — сатурация (SpO₂) в макете
    # есть отдельной колонкой, в модели её не было вообще (только АД/
    # пульс/температура). Проценты, как и остальные показатели —
    # необязательное поле, но валидируем диапазон 0-100 (clean() ниже),
    # это не просто число, а физический процент.
    spo2 = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(100)], verbose_name="Сатурация (SpO₂), %"
    )
    note = models.CharField(max_length=255, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["admission", "-recorded_at"])]

    def __str__(self):
        return f"{self.admission} @ {self.recorded_at:%Y-%m-%d %H:%M}"

    @property
    def department(self):
        return self.admission.department

    def clean(self):
        if not any([
            self.blood_pressure_systolic is not None,
            self.blood_pressure_diastolic is not None,
            self.pulse is not None,
            self.temperature is not None,
            self.spo2 is not None,
        ]):
            raise ValidationError("Нужно указать хотя бы один показатель.")
        if self.admission_id and self.admission.status != AdmissionStatus.ACTIVE:
            raise ValidationError("Нельзя добавить замер для завершённой госпитализации.")


class OperatingRoom(models.Model):
    """Операционная — расписываемый ресурс филиала (как Appointment
    бронирует врача, Operation бронирует операционную), а не палата с
    койками: Room/Bed моделируют пребывание пациента, операционная —
    только слот времени. Не привязана к одному Department — операционная
    обычно обслуживает несколько отделений сразу, поэтому это ресурс
    ФИЛИАЛА (branch), тот же уровень, что структура Room/Bed, поэтому
    управление ею (CRUD) идёт через тот же inpatient.department.manage,
    а не отдельный код.
    """

    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="operating_rooms"
    )
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["branch_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="unique_operating_room_name_per_branch"),
        ]

    def __str__(self):
        return f"{self.name} ({self.branch})"


class OperationStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Запланирована"
    COMPLETED = "completed", "Завершена"
    CANCELLED = "cancelled", "Отменена"


OPERATION_TERMINAL_STATUSES = (OperationStatus.COMPLETED, OperationStatus.CANCELLED)


class Operation(models.Model):
    """Операционный модуль — привязан к Admission (только стационарные
    операции, амбулаторная хирургия вне рамок этой фазы). Самое сложное
    в шаге (f), по договорённости проработано отдельно от остальной
    структуры: чек-лист безопасности хирургии — три обязательные,
    строго последовательные фазы (Sign In / Time Out / Sign Out, тот же
    состав, что общепринятый чек-лист ВОЗ), а не свободный JSONField —
    в отличие от Visit.diagnosis_snapshot (где структуры заведомо нет и
    не будет), здесь структура фиксированная и известная заранее, так
    что каждая фаза — собственная пара «кто подтвердил / когда», и
    Operation.complete() физически не даст завершить операцию, если
    Sign Out не подтверждён — это и есть смысл чек-листа безопасности,
    не просто галочка в интерфейсе.
    """

    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="operations")
    operating_room = models.ForeignKey(OperatingRoom, on_delete=models.PROTECT, related_name="operations")
    procedure_name = models.CharField(max_length=255, verbose_name="Операция")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    lead_surgeon = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="operations_led"
    )
    team = models.ManyToManyField(
        "accounts.User", blank=True, related_name="operations_assisted",
        help_text="Остальной состав операционной бригады.",
    )
    status = models.CharField(
        max_length=20, choices=OperationStatus.choices, default=OperationStatus.SCHEDULED
    )

    # Чек-лист безопасности хирургии — три фазы, каждая со своим
    # подтверждающим и временем. Порядок соблюдается методами
    # confirm_sign_in/confirm_time_out/confirm_sign_out ниже, не только
    # проверкой на фронте.
    sign_in_confirmed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    sign_in_confirmed_at = models.DateTimeField(null=True, blank=True)
    time_out_confirmed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    time_out_confirmed_at = models.DateTimeField(null=True, blank=True)
    sign_out_confirmed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    sign_out_confirmed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["operating_room", "starts_at"]),
            models.Index(fields=["admission", "status"]),
        ]

    def __str__(self):
        return f"{self.procedure_name} — {self.admission} ({self.get_status_display()})"

    @property
    def department(self):
        return self.admission.department

    def clean(self):
        if self.pk:
            original_status = (
                Operation.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if original_status in OPERATION_TERMINAL_STATUSES:
                # Закрытая операция неизменяема целиком (не только статус)
                # — тот же принцип, что делает Payment/Transfer append-only:
                # хирургический протокол после завершения/отмены — история,
                # не черновик, который можно поправить задним числом.
                raise ValidationError(
                    "Операция уже закрыта (%s) — изменения невозможны."
                    % OperationStatus(original_status).label
                )
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError("Начало операции должно быть раньше окончания.")
        if self.operating_room_id and self.starts_at and self.ends_at:
            # Тот же приём, что Appointment.clean()'s overlap-check —
            # двойное бронирование операционной на пересекающееся время
            # отклоняется (чек-лист Фазы 4 требует это явно).
            overlapping = (
                Operation.objects.filter(
                    operating_room_id=self.operating_room_id,
                    starts_at__lt=self.ends_at,
                    ends_at__gt=self.starts_at,
                )
                .exclude(status__in=OPERATION_TERMINAL_STATUSES)
                .exclude(pk=self.pk)
                .exists()
            )
            if overlapping:
                raise ValidationError(
                    {"operating_room": "Операционная уже забронирована на пересекающееся время."}
                )

    def confirm_sign_in(self, user) -> bool:
        """No-op-safe re-submit (returns False if already confirmed) —
        same shape as every other terminal/idempotent transition in this
        project, so a retried request can't silently overwrite who
        actually confirmed it."""
        if self.sign_in_confirmed_at is not None:
            return False
        self.sign_in_confirmed_by = user
        self.sign_in_confirmed_at = timezone.now()
        self.save(update_fields=["sign_in_confirmed_by", "sign_in_confirmed_at", "updated_at"])
        return True

    def confirm_time_out(self, user) -> bool:
        if self.sign_in_confirmed_at is None:
            raise ValidationError("Сначала нужно подтвердить Sign In.")
        if self.time_out_confirmed_at is not None:
            return False
        self.time_out_confirmed_by = user
        self.time_out_confirmed_at = timezone.now()
        self.save(update_fields=["time_out_confirmed_by", "time_out_confirmed_at", "updated_at"])
        return True

    def confirm_sign_out(self, user) -> bool:
        if self.time_out_confirmed_at is None:
            raise ValidationError("Сначала нужно подтвердить Time Out.")
        if self.sign_out_confirmed_at is not None:
            return False
        self.sign_out_confirmed_by = user
        self.sign_out_confirmed_at = timezone.now()
        self.save(update_fields=["sign_out_confirmed_by", "sign_out_confirmed_at", "updated_at"])
        return True

    def complete(self) -> bool:
        """SCHEDULED -> COMPLETED. Physically refuses without a confirmed
        Sign Out — the actual point of a surgical safety checklist, not
        just a UI checkbox."""
        if self.status in OPERATION_TERMINAL_STATUSES:
            return False
        if self.sign_out_confirmed_at is None:
            raise ValidationError(
                "Нельзя завершить операцию без подтверждённого Sign Out (чек-лист безопасности)."
            )
        self.status = OperationStatus.COMPLETED
        self.save(update_fields=["status", "updated_at"])
        return True

    def cancel(self) -> bool:
        if self.status in OPERATION_TERMINAL_STATUSES:
            return False
        self.status = OperationStatus.CANCELLED
        self.save(update_fields=["status", "updated_at"])
        return True
