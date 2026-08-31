from django.core.exceptions import ValidationError
from django.db import models


class ChurnRiskStatus(models.TextChoices):
    NEW = "new", "Новый"
    ACKNOWLEDGED = "acknowledged", "Принято в работу"
    REACTIVATED = "reactivated", "Пациент вернулся"
    DISMISSED = "dismissed", "Отклонено"


# REACTIVATED/DISMISSED закрывают эпизод — тот же TERMINAL_STATUSES-приём,
# что Referral/LabOrder/Admission/ClinicalOrder/Operation. NEW/ACKNOWLEDGED
# считаются "активными" пересчитывающейся таской (apps.churn.services.
# calculate_churn_risks) — именно их она обновляет на месте при повторном
# запуске, а не плодит дубликаты на каждый прогон.
TERMINAL_STATUSES = (ChurnRiskStatus.REACTIVATED, ChurnRiskStatus.DISMISSED)


class ChurnRisk(models.Model):
    """Алерт "пациент, вероятно, отваливается" — простая эвристика на
    старте (Фаза 5, под-модуль 1), не ML: "не был на приёме дольше
    среднего межвизитного интервала". Отдельная сущность БЕЗ интеграции
    с CRM-модулем — в проекте такого модуля нет (решение зафиксировано в
    чате перед стартом; появится CRM — ChurnRisk станет для неё
    источником данных).

    Один активный (NEW/ACKNOWLEDGED) алерт на пациента — задача
    обновляет существующий на месте вместо дублирования; при возврате
    пациента (новый COMPLETED-визит после last_visit_date) задача сама
    переводит активный алерт в REACTIVATED — координатору не нужно
    закрывать его вручную, только если он ошибочный (dismiss()).
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="churn_risks"
    )
    # Снапшот филиала последнего завершённого визита на момент расчёта —
    # пациент сам сетевой (apps.patients.Patient), но "кто у нас давно не
    # приходил" — операционный вопрос конкретного филиала, поэтому здесь
    # обычный branch-scoped RBAC (HasBranchPermission), тот же паттерн,
    # что везде в проекте, а не HasPermission как у самой карты пациента.
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="churn_risks"
    )
    last_visit_date = models.DateTimeField(
        verbose_name="Дата последнего визита",
        help_text="Visit.created_at последнего COMPLETED-визита пациента.",
    )
    avg_interval_days = models.FloatField(
        verbose_name="Средний межвизитный интервал (дней)",
        help_text="Средний интервал между завершёнными визитами пациента.",
    )
    days_overdue = models.PositiveIntegerField(
        verbose_name="Просрочено дней",
        help_text="На сколько дней пациент превысил свой обычный интервал визитов.",
    )
    risk_score = models.FloatField(
        verbose_name="Оценка риска",
        help_text="days_overdue / avg_interval_days — простая формула, не ML-модель. "
        "1.0 = просрочен ровно на один свой обычный интервал, выше — больше.",
    )
    status = models.CharField(
        max_length=20, choices=ChurnRiskStatus.choices, default=ChurnRiskStatus.NEW
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-risk_score"]
        indexes = [
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["patient", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.patient} — просрочено {self.days_overdue} дн. ({self.get_status_display()})"

    def clean(self):
        if self.pk:
            original_status = (
                ChurnRisk.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if original_status in TERMINAL_STATUSES and original_status != self.status:
                raise ValidationError(
                    "Алерт уже закрыт (%s) — статус больше нельзя менять."
                    % ChurnRiskStatus(original_status).label
                )

    def acknowledge(self) -> bool:
        """NEW -> ACKNOWLEDGED. No-op-safe (returns False if not NEW) —
        same shape as every other status transition in this project."""
        if self.status != ChurnRiskStatus.NEW:
            return False
        self.status = ChurnRiskStatus.ACKNOWLEDGED
        self.save(update_fields=["status", "updated_at"])
        return True

    def dismiss(self) -> bool:
        if self.status in TERMINAL_STATUSES:
            return False
        self.status = ChurnRiskStatus.DISMISSED
        self.save(update_fields=["status", "updated_at"])
        return True

    def reactivate(self) -> bool:
        """Обычно вызывается автоматически из calculate_churn_risks при
        обнаружении нового визита после last_visit_date, но доступен и
        как ручное действие (координатор дозвонился, пациент подтвердил
        визит раньше, чем это увидит следующий прогон таски)."""
        if self.status in TERMINAL_STATUSES:
            return False
        self.status = ChurnRiskStatus.REACTIVATED
        self.save(update_fields=["status", "updated_at"])
        return True
