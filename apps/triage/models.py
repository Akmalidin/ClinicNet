from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class TriageChannel(models.TextChoices):
    TELEGRAM = "telegram", "Telegram"
    # WHATSAPP — второй канал сознательно не заведён на первом шаге
    # (см. разведку Фазы 5 под-модуля 2: WhatsApp Business API требует
    # одобрения Meta и бизнес-аккаунта, Telegram выбран для старта).


class TriageSuggestionStatus(models.TextChoices):
    PENDING = "pending", "Ожидает подтверждения"
    CONFIRMED = "confirmed", "Подтверждено"
    REJECTED = "rejected", "Отклонено"
    EXPIRED = "expired", "Слот больше не актуален"


TERMINAL_STATUSES = (
    TriageSuggestionStatus.CONFIRMED,
    TriageSuggestionStatus.REJECTED,
    TriageSuggestionStatus.EXPIRED,
)


class TriageSuggestion(models.Model):
    """Предложение AI-триажа — пациент описал жалобу в чат-боте, LLM/
    эвристика подобрала специальность, отдельный сервис (triage_service/,
    FastAPI) нашёл ближайший свободный слот через уже существующий
    apps.referrals available_slots и создал эту запись через ingest-API
    ниже. "Координатор только подтверждает, не вводит вручную" (прямое
    требование промпта фазы) — эта запись НЕ бронирует приём сама по
    себе, только предлагает; реальный scheduling.Appointment создаётся
    методом confirm() ниже, вызванным координатором, который сам решает,
    к какому Patient это относится (см. confirm()'s докстринг — почему
    сопоставление с пациентом не автоматическое).
    """

    channel = models.CharField(
        max_length=20, choices=TriageChannel.choices, default=TriageChannel.TELEGRAM
    )
    external_chat_id = models.CharField(
        max_length=64, verbose_name="ID чата в канале",
        help_text="Например, Telegram chat_id — куда отправить ответ пациенту.",
    )
    contact_name = models.CharField(max_length=200, blank=True, verbose_name="Имя из чата")
    contact_phone = models.CharField(max_length=32, blank=True, verbose_name="Телефон из чата")
    symptom_text = models.TextField(verbose_name="Жалоба пациента (как есть, из чата)")

    matched_specialty = models.ForeignKey(
        "accounts.Specialty", on_delete=models.PROTECT, related_name="triage_suggestions"
    )
    # "branch" (не "suggested_branch") специально — так apps.accounts.
    # permissions.HasBranchPermission резолвит филиал и на create (из
    # request.data["branch"]), и на object-level (через obj.branch) без
    # доработок, тот же механизм, что везде в проекте.
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="triage_suggestions"
    )
    suggested_doctor = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="triage_suggestions"
    )
    suggested_starts_at = models.DateTimeField()
    suggested_ends_at = models.DateTimeField()
    # 0-100, самооценка классификатора (triage_service/classifier.py) —
    # для эвристики KeywordSpecialtyClassifier это условная эвристика по
    # числу совпавших ключевых слов, не заявка на клиническую точность
    # (тот же принцип упрощения, что у ChurnRisk.risk_score); для
    # AnthropicSpecialtyClassifier — то, что вернула сама модель. null у
    # предложений, созданных до этого поля. Только для того, чтобы
    # координатор видел, насколько бот уверен, и мог решить, стоит ли
    # перепроверить/сменить слот, а не автоматически что-то менять.
    match_confidence = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Уверенность классификатора (%)",
    )

    status = models.CharField(
        max_length=20, choices=TriageSuggestionStatus.choices, default=TriageSuggestionStatus.PENDING
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True,
        related_name="triage_suggestions",
    )
    resulting_appointment = models.OneToOneField(
        "scheduling.Appointment", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="triage_suggestion",
    )
    confirmed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["channel", "external_chat_id"]),
        ]

    def __str__(self):
        return f"{self.contact_name or self.external_chat_id} → {self.matched_specialty} ({self.get_status_display()})"

    def clean(self):
        if self.pk:
            original_status = (
                TriageSuggestion.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if original_status in TERMINAL_STATUSES and original_status != self.status:
                raise ValidationError(
                    "Предложение уже закрыто (%s) — статус больше нельзя менять."
                    % TriageSuggestionStatus(original_status).label
                )

    def confirm(self, confirmed_by, patient, doctor=None, starts_at=None, ends_at=None) -> bool:
        """Создаёт реальный scheduling.Appointment и закрывает
        предложение. `patient` передаётся координатором явно (не
        auto-matching по телефону из чата) — телефон, который человек
        печатает в Telegram, слишком ненадёжен для тихого связывания с
        медицинской картой без подтверждения; координатор либо находит
        существующего Patient (обычный поиск, который уже есть в UI),
        либо сперва заводит нового через уже существующий
        patient.manage-флоу, а потом подтверждает предложение с его id.

        doctor/starts_at/ends_at — «Изменить слот»: координатор может
        подтвердить на ДРУГОГО врача/время (тот же филиал), не только на
        то, что предложил бот — например, если предложенный бота слот
        уже неудобен пациенту, или уверенность классификатора низкая и
        координатор сам подобрал более подходящего врача. Оставлены
        необязательными — без них поведение не меняется.

        No-op-safe: возвращает False, если предложение уже закрыто, ИЛИ
        если итоговый слот (с учётом возможной замены) уже в прошлом —
        для оригинального слота бота это переводит предложение в EXPIRED
        (как раньше), для явно переданной координатором замены — просто
        отказ, без побочных эффектов (координатор сам ошибся в форме, не
        бот устарел). Appointment.clean()'s собственная проверка
        пересечений подтвердит (или отклонит), что слот с момента
        предложения не был занят кем-то другим — та же защита, что уже
        есть у Appointment.
        """
        from apps.scheduling.models import Appointment

        if self.status in TERMINAL_STATUSES:
            return False

        is_override = doctor is not None or starts_at is not None or ends_at is not None
        use_doctor = doctor or self.suggested_doctor
        use_starts = starts_at or self.suggested_starts_at
        use_ends = ends_at or self.suggested_ends_at

        if use_starts <= timezone.now():
            if not is_override:
                self.status = TriageSuggestionStatus.EXPIRED
                self.save(update_fields=["status", "updated_at"])
            return False

        appointment = Appointment(
            branch=self.branch,
            patient=patient,
            doctor=use_doctor,
            starts_at=use_starts,
            ends_at=use_ends,
            notes=f"Создано через AI-триаж (Telegram). Жалоба: {self.symptom_text}",
        )
        appointment.full_clean()
        appointment.save()

        self.patient = patient
        self.resulting_appointment = appointment
        self.status = TriageSuggestionStatus.CONFIRMED
        self.confirmed_by = confirmed_by
        self.confirmed_at = timezone.now()
        self.full_clean()
        self.save(update_fields=[
            "patient", "resulting_appointment", "status", "confirmed_by", "confirmed_at", "updated_at",
        ])
        return True

    def reject(self, reason: str = "") -> bool:
        if self.status in TERMINAL_STATUSES:
            return False
        self.status = TriageSuggestionStatus.REJECTED
        if reason:
            self.rejection_reason = reason
        self.save(update_fields=["status", "rejection_reason", "updated_at"])
        return True
