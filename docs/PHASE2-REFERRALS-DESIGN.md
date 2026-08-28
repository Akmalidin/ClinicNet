# Фаза 2 (первый срез) — Единая ЭМК + модели «Направлений»: отчёт и дизайн

Статус: **модели/миграции реализованы и проверены** на реальном Postgres (schema-per-tenant), API/actions/уведомления — следующий срез (см. «Что дальше» в конце).

## 1. Разведка: с каким кодом реально сверялись

Стартовый промпт этой фазы (`docs/ClinicNet-Phase2-Starter-Prompt.md`) явно предупреждает не полагаться на память о других проектах. Разведка была сделана против фактического состояния `main` (коммит Фазы 1, без дрейфа — проверено `git diff HEAD origin/main`), а не по памяти:

- Реальные поля `Appointment`: `starts_at`/`ends_at` (не `start_at`/`end_at`, как в некоторых других проектах).
- RBAC — собственная система (`apps.accounts.rbac`, `UserRole.branch_scope`), не Django `has_perm()`.
- Ни `django-fsm`, ни WhatsApp/Telegram-сервиса, ни Celery/Redis в проекте нет — Фаза 1 их не создавала.

Полный список расхождений спеки `ClinicNet-Referrals-Prompt.md` с реальным кодом — в конце этого файла и в самой спеке (раздел «Как это реализовано в ClinicNet»).

## 2. Найденный и исправленный баг: карта пациента

`apps/patients/views.py::PatientViewSet.get_queryset` в Фазе 1 фильтровал сам список пациентов по `primary_branch` (видимым пользователю филиалам) — пациент вне видимых филиалов не просто "терял" записи, а пропадал целиком (404 на detail, отсутствие в списке). Это ровно тот баг, который явно предвидел стартовый промпт: "карта = один филиал" по факту была.

**Исправлено:** `patient.view`/`patient.manage` в любом scope (даже `own_branch`) теперь открывает весь список пациентов сети — `get_queryset` вернулся к `Patient.objects.all()`, авторизация осталась на `HasPermission` (уже была branch-agnostic). `primary_branch` остался как справочное поле и опциональный фильтр (`?primary_branch=`), но перестал быть тихим ограничением видимости. Branch-scoping по-прежнему применяется к тому, что *внутри* карты — `Appointment`/`Visit`/`Referral` остаются отфильтрованы по филиалу как обычно.

Регрессионный тест на HTTP-уровне (не просто на уровне queryset) — `apps/patients/tests.py::PatientCardIsNetworkWideTests`, плюс проверено вручную через `curl` с реальным JWT: врач с доступом только к филиалу А теперь видит пациента, зарегистрированного в филиале Б.

## 3. Единая ЭМК: модель `Visit`

`apps/visits.Visit` — клиническая запись приёма (в отличие от `scheduling.Appointment`, который остаётся просто календарным слотом): `patient`, `doctor`, `branch`, опциональный `appointment` (если приём был по записи — иначе walk-in), `reason`, `clinical_note`, `diagnosis_snapshot` (JSONField — в проекте пока нет отдельной модели одонтограммы/диагноза, которую можно было бы структурированно снимать, поэтому пока свободная форма), `status` (`in_progress`/`completed`/`cancelled`, обычный `CharField(choices=...)` — как и везде в проекте, без FSM), `close()` — помощник, аналогичный `Referral.mark_completed()`.

Права: `visit.view`/`visit.manage`, тот же branch-scoped паттерн, что и у `appointment.*`.

Это решение было согласовано отдельно (см. переписку) как рекомендованное — без него `Referral.source_visit` было не на что ссылаться (в спеке предполагалась модель `Visit`, которой в проекте не было).

## 4. Модуль направлений: модели

`apps/referrals.Referral` — реализован по спеке `ClinicNet-Referrals-Prompt.md` разделы 1–2 почти без изменений полей, с пятью согласованными расхождениями:

| Что в спеке | Что в ClinicNet | Почему |
|---|---|---|
| `source_visit → visits.Visit` | То же самое | `Visit` введён в этом же заходе (см. п. 3) — совпадение полное. |
| `to_specialty → staff.Specialty` | `to_specialty → accounts.Specialty` | Отдельного приложения `staff` в проекте нет; специализация — атрибут `User`, поэтому справочник живёт в `accounts`. Добавлен `User.specialties` (M2M) — без него `to_specialty` было бы нечем подбирать (не по чему матчить врачей). |
| RBAC через `user.has_perm("referrals.view_all_branches")` и т.п. (3+ отдельных кода) | `referrals.view`/`referrals.manage` (2 кода) + `branch_scope` на `UserRole` | Согласовано: "видит своё" (то, что сам отправил/получил) — не отдельный permission-код, а базовое поведение вьюсета для любого аутентифицированного врача (ровно как в спековском `get_queryset`, просто не завязано на doubling с branch_scope). `view_branch`/`view_all_branches` избыточны поверх уже существующего `branch_scope` (own_branch/all). |
| Celery-таски (`notify_*`, `escalate_stale_referrals` в beat) | Синхронные уведомления + management-команда под cron (в этом заходе моделей — ещё не реализовано, задел оставлен) | В проекте нет Celery/Redis; поднимать инфраструктуру ради трёх тасков признано избыточным для этой фазы. |
| Vue-компоненты (раздел 6) | Не реализовано | ClinicNet — чистый DRF-бэкенд без единой строчки фронтенда; поднятие Vue 3 с нуля — отдельная, самостоятельная задача. |

Модель `Referral` включает валидацию на уровне `clean()` (не только сериализатора, как в спеке — это соответствует паттерну проекта, см. `Appointment.clean()`/`StaffBranchAssignment.clean()` из Фазы 1):
- обязателен `to_doctor` **или** `to_specialty`;
- при `status=DECLINED` обязателен `outcome_note` (это же явно требует чек-лист ручной проверки фазы).

`mark_completed()` — как в спеке, дословно.

## 5. Как проверено

* `python manage.py makemigrations --check` — чисто.
* Полный цикл на реальном Postgres 16, схема `demo_clinic` (та же, что и в Фазе 1): `migrate_schemas --schema=demo_clinic` → `tenant_command seed_rbac` (идемпотентно добавил `visit.view/manage`, `referrals.view/manage`) → ручной smoke-test через `tenant_command shell`:
  - внутрифилиальное направление (`from_branch == to_branch`) — валидно;
  - кросс-филиальное направление — валидно, `is_cross_branch`-эквивалент (`from_branch_id != to_branch_id`) считается верно;
  - направление "на специальность" без `to_doctor` — валидно;
  - направление без `to_doctor` и без `to_specialty` — отклонено `ValidationError`;
  - отклонение (`DECLINED`) без `outcome_note` — отклонено `ValidationError`; с `outcome_note` — проходит;
  - `mark_completed()` — статус/`completed_at`/`outcome_note` проставляются верно.
* То же самое через реальный HTTP (`runserver` + `curl` с JWT и Host-заголовком тенант-домена) для найденного бага карты пациента — до и после исправления.
* Автотесты (`TenantTestCase`, реальная Postgres-схема на каждый прогон): `apps/patients/tests.py` (регрессия бага карты), `apps/visits/tests.py`, `apps/referrals/tests.py` — 27 тестов всего (16 из Фазы 1 + 11 новых), все зелёные.

## 6. Что дальше (не в этом заходе)

По плану («Последовательность реализации» шаги 2–9 из спеки, адаптированные под этот проект):
- Сериализаторы + `ReferralViewSet` (базовый CRUD) + `HasReferralPermission` (нужен отдельный класс — у `Referral` два филиала, `from_branch`/`to_branch`, а не один `.branch`, как у `Appointment`/`StaffBranchAssignment`, поэтому существующий `HasBranchPermission` не подходит напрямую).
- `schedule`/`decline`/`complete` actions + сигнал на `Appointment.status → completed`.
- Внутренний `Notification`-объект (без реального WA/Telegram-провода) + `escalate_stale_referrals` management-команда.
- `available-slots` — новая логика (смены `StaffBranchAssignment` минус занятые `Appointment`), в спеке это "прокси", но переиспользовать в проекте нечего.
- (c) Базовая диагностика — `LabOrder`/`LabResult`, отдельным заходом.
- Frontend — вне текущего скоупа, отдельная задача по явному запросу.
