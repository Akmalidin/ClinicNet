# ClinicNet — Модуль «Направления» (Referral)
## Implementation-ready промпт для Claude Code

Контекст: Django 5.1 + DRF, Vue 3 + Vite + TailwindCSS, PostgreSQL 16 + django-tenants (schema-per-organization), Celery + Redis, S3. Направление — это объект-мост между двумя врачами (в одном филиале или в разных), который несёт контекст визита и трекается до закрытия.

---

## 1. Модель данных

Приложение: `referrals` (новое, внутри схемы тенанта — доступно всем филиалам организации).

```python
# referrals/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone


class ReferralStatus(models.TextChoices):
    PENDING = "pending", "Ожидает"          # создано, слот ещё не выбран/не подтверждён
    SCHEDULED = "scheduled", "Запланировано" # подтверждён слот у принимающего врача
    ACCEPTED = "accepted", "Принято"         # пациент пришёл, приём начат
    COMPLETED = "completed", "Завершено"     # приём у принимающего врача закрыт
    DECLINED = "declined", "Отклонено"       # принимающий врач/координатор отклонил
    CANCELLED = "cancelled", "Отменено"      # отменено направившим врачом или пациентом


class ReferralPriority(models.TextChoices):
    ROUTINE = "routine", "Плановое"
    URGENT = "urgent", "Срочное"
    EMERGENCY = "emergency", "Экстренное"


class Referral(models.Model):
    # Кто и куда
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="referrals")
    from_doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="referrals_sent")
    to_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="referrals_received",
        null=True, blank=True,  # null = направлено "на специальность", конкретный врач не выбран
    )
    to_specialty = models.ForeignKey("staff.Specialty", on_delete=models.PROTECT, null=True, blank=True)

    from_branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="referrals_out")
    to_branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="referrals_in")

    # Контекст визита (снапшот на момент направления — не ссылка "вживую",
    # чтобы принимающий врач видел карту такой, какой она была при направлении)
    source_visit = models.ForeignKey("visits.Visit", on_delete=models.SET_NULL, null=True, related_name="referrals")
    reason = models.CharField(max_length=255)                  # "Ортодонтическая консультация"
    clinical_note = models.TextField(blank=True)                 # жалобы/осмотр/диагноз на момент направления
    diagnosis_snapshot = models.JSONField(default=dict, blank=True)  # МКБ-10 коды, одонтограмма-снапшот и т.п.

    # Связка с реальной записью, когда слот выбран
    target_appointment = models.OneToOneField(
        "scheduling.Appointment", on_delete=models.SET_NULL, null=True, blank=True, related_name="referral"
    )

    status = models.CharField(max_length=20, choices=ReferralStatus.choices, default=ReferralStatus.PENDING)
    priority = models.CharField(max_length=20, choices=ReferralPriority.choices, default=ReferralPriority.ROUTINE)

    # Обратная связь принимающего врача направившему
    outcome_note = models.TextField(blank=True)
    outcome_visible_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", help_text="Обычно = from_doctor, но можно переопределить"
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

    def mark_completed(self, outcome_note: str = ""):
        self.status = ReferralStatus.COMPLETED
        self.completed_at = timezone.now()
        if outcome_note:
            self.outcome_note = outcome_note
        self.save(update_fields=["status", "completed_at", "outcome_note", "updated_at"])
```

**Почему снапшот, а не live-ссылка на карту:** принимающий врач должен видеть ровно тот контекст, который был на момент направления — если направивший врач позже дополнит карту, это не должно "задним числом" менять то, что уже увидел коллега. Полная живая карта пациента остаётся доступна отдельным переходом ("Открыть полную карту"), это не заменяется снапшотом.

---

## 2. Переходы статусов (state machine, упрощённо)

```
PENDING → SCHEDULED   (координатор/принимающий врач подтвердил слот → target_appointment проставлен)
PENDING → DECLINED    (принимающий врач/координатор отклонил, обязателен outcome_note с причиной)
PENDING → CANCELLED   (направивший врач или пациент отменили до подтверждения слота)
SCHEDULED → ACCEPTED  (пациент отмечен "пришёл" на target_appointment)
ACCEPTED → COMPLETED  (принимающий врач закрыл приём → mark_completed())
любой → CANCELLED     (кроме COMPLETED — завершённое направление неизменяемо)
```

Реализовать как `django-fsm` (уже используется в проекте для статусов приёма — уточнить) либо простым `clean()`-валидатором переходов в сериализаторе, если FSM не используется нигде ещё.

---

## 3. API (DRF)

```python
# referrals/serializers.py
class ReferralSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    from_doctor_name = serializers.CharField(source="from_doctor.get_full_name", read_only=True)
    to_doctor_name = serializers.CharField(source="to_doctor.get_full_name", read_only=True, allow_null=True)
    from_branch_name = serializers.CharField(source="from_branch.name", read_only=True)
    to_branch_name = serializers.CharField(source="to_branch.name", read_only=True)
    is_cross_branch = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = [
            "id", "patient", "patient_name",
            "from_doctor", "from_doctor_name", "to_doctor", "to_doctor_name", "to_specialty",
            "from_branch", "from_branch_name", "to_branch", "to_branch_name",
            "reason", "clinical_note", "diagnosis_snapshot", "priority", "status",
            "target_appointment", "outcome_note",
            "created_at", "updated_at", "scheduled_at", "completed_at", "is_cross_branch",
        ]
        read_only_fields = ["status", "created_at", "updated_at", "completed_at"]

    def get_is_cross_branch(self, obj):
        return obj.from_branch_id != obj.to_branch_id

    def validate(self, attrs):
        if not attrs.get("to_doctor") and not attrs.get("to_specialty"):
            raise serializers.ValidationError("Укажите принимающего врача или специальность.")
        return attrs
```

```python
# referrals/views.py
class ReferralViewSet(viewsets.ModelViewSet):
    serializer_class = ReferralSerializer
    permission_classes = [IsAuthenticated, HasReferralPermission]  # см. раздел RBAC

    def get_queryset(self):
        user = self.request.user
        qs = Referral.objects.select_related(
            "patient", "from_doctor", "to_doctor", "from_branch", "to_branch"
        )
        # Врач по умолчанию видит: что сам направил + что направлено ему
        if not user.has_perm("referrals.view_all_branches"):
            qs = qs.filter(models.Q(from_doctor=user) | models.Q(to_doctor=user))
        # Фильтры из query params
        if branch_id := self.request.query_params.get("branch"):
            qs = qs.filter(models.Q(from_branch_id=branch_id) | models.Q(to_branch_id=branch_id))
        if status_ := self.request.query_params.get("status"):
            qs = qs.filter(status=status_)
        if cross_only := self.request.query_params.get("cross_branch_only"):
            qs = qs.exclude(from_branch=models.F("to_branch"))
        return qs

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        """Подтвердить слот у принимающего врача — привязать target_appointment."""
        ...

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        """Требует outcome_note с причиной отказа."""
        ...

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Вызывается при закрытии target_appointment принимающим врачом."""
        ...
```

**Эндпоинты:**
- `GET /api/referrals/?status=pending&branch={id}` — очередь направлений (для дашборда координатора/сети)
- `POST /api/referrals/` — создать направление из карты пациента
- `POST /api/referrals/{id}/schedule/` — подтвердить слот
- `POST /api/referrals/{id}/decline/`
- `POST /api/referrals/{id}/complete/` — либо вызывать автоматически из сигнала при закрытии `target_appointment`
- `GET /api/referrals/available-slots/?doctor={id}&date={date}` — прокси к модулю расписания, чтобы UI сразу предлагало свободные окна принимающего врача

---

## 4. RBAC — новые права

Добавить в матрицу `permissions` (роль × право):

| Право | Кому по умолчанию |
|---|---|
| `referrals.create` | Врач |
| `referrals.view_own` | Врач (видит то, что сам отправил/получил) |
| `referrals.view_branch` | Администратор/координатор филиала |
| `referrals.view_all_branches` | Директор сети, администратор сети |
| `referrals.reassign` | Координатор филиала (переназначить на другого врача, если принимающий недоступен) |
| `referrals.decline` | Принимающий врач, координатор |

---

## 5. Уведомления (Celery)

```python
# referrals/tasks.py
@shared_task
def notify_referral_created(referral_id):
    """WhatsApp/Telegram принимающему врачу + запись в internal inbox."""
    ...

@shared_task
def notify_referral_completed(referral_id):
    """Уведомление направившему врачу с outcome_note, когда принимающий закрыл приём."""
    ...

@shared_task
def escalate_stale_referrals():
    """Celery beat, раз в час: PENDING > 24ч → уведомление координатору филиала
    (это и есть источник данных для виджета 'Направления ожидают > 24 часов' на дашборде сети)."""
    ...
```

Сигнал: при `Appointment.status → completed`, если у `Appointment` есть привязанный `Referral`, вызвать `referral.mark_completed()` + `notify_referral_completed.delay(referral.id)`.

---

## 6. Frontend (Vue 3)

**Компоненты:**

1. **`ReferralModal.vue`** — открывается из карты пациента кнопкой «Направить».
   - Шаг 1: выбор специальности/врача (поиск с фильтром "в этом филиале" / "показать всю сеть")
   - Шаг 2: если выбран конкретный врач → показ его свободных слотов (`GET /available-slots/`) на ближайшие 3 дня
   - Шаг 3: причина направления + клиническая заметка (предзаполняется текущим осмотром, редактируется)
   - Submit → `POST /api/referrals/`, если слот выбран — сразу `schedule`

2. **`ReferralQueueWidget.vue`** — переиспользуемый виджет (уже нужен на дашборде сети, см. `network-dashboard.html`).
   - Пропсы: `scope: 'branch' | 'network'`, `statusFilter`
   - Таблица: пациент / от кого / кому-куда / причина / статус / приоритет
   - Клик по строке → быстрые действия (принять/отклонить/перенести)

3. **`ReferralBadge.vue`** — маленький бейдж на карточке приёма в расписании (`multi-branch-schedule.html`), если приём создан из направления — показывает иконку + tooltip с `reason` и именем направившего врача.

4. **Composable `useReferrals.ts`** — `fetchQueue()`, `createReferral()`, `scheduleReferral()`, `declineReferral()`, с кэшированием через существующий query-слой проекта (уточнить, используется ли уже Vue Query/Pinia для API-кэша).

**State для UI:** статус направления влияет на цвет строки в очереди — тот же токен-набор, что и в `network-dashboard.html` (mint = ok/scheduled, amber = pending, red = urgent/declined).

---

## 7. Последовательность реализации

1. Модели `Referral` + миграция + admin-регистрация для ручной проверки
2. Сериализаторы + `ReferralViewSet` без custom actions (базовый CRUD) + RBAC-права
3. `schedule` / `decline` / `complete` actions + сигнал на `Appointment.status`
4. Celery-таски уведомлений + `escalate_stale_referrals` в beat-расписание
5. `ReferralModal.vue` — создание направления из карты пациента (внутри филиала, самый частый кейс)
6. Расширение модалки на кросс-филиальный выбор (специальность → филиал → врач)
7. `ReferralQueueWidget.vue` на дашборд филиала и дашборд сети
8. `ReferralBadge.vue` на расписании
9. `available-slots` эндпоинт как прокси к модулю расписания (если ещё не переиспользуется откуда-то ещё)

---

## 8. Что уточнить перед стартом

- Используется ли уже `django-fsm` в проекте для статусов `Appointment` — если да, привести `Referral.status` к тому же паттерну для консистентности.
- Есть ли уже общий inbox/уведомления модуль (для WhatsApp/Telegram) — переиспользовать сервис отправки, не дублировать.
- Формат `diagnosis_snapshot` — зависит от текущей структуры одонтограммы в проекте, нужно свериться с реальной моделью `Visit`/`Diagnosis`.

---

## Как это реализовано в ClinicNet (см. `docs/PHASE2-REFERRALS-DESIGN.md`)

Пять расхождений между этой спекой и реальным кодом ClinicNet после Фазы 1, и как они разрешены:

1. `visits.Visit` не существовал — введён в Фазе 2 как отдельная модель клинической записи (см. `apps/visits`).
2. `staff.Specialty` не существовал — введён как `accounts.Specialty` + `User.specialties` (M2M).
3. RBAC — не через `user.has_perm(...)` (встроенный Django), а через собственную систему `apps.accounts.rbac` (`branch_scope` на `UserRole`). Матрица прав свёрнута до одного кода `referrals.view`/`referrals.manage` — "видит своё" не отдельный permission-код, а базовое поведение queryset для любого аутентифицированного врача.
4. Celery/Redis не подняты — уведомления синхронные, `escalate_stale_referrals` — management-команда под cron, не Celery beat.
5. Frontend (раздел 6) — не реализован в этом заходе: ClinicNet сейчас чистый DRF-бэкенд, поднятие Vue 3 с нуля — отдельная, самостоятельная задача.
