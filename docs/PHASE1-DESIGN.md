# Фаза 1 — Фундамент: отчёт и дизайн

Статус: **реализовано и протестировано** на реальном Postgres (schema-per-tenant), готово к ревью.

## 1. Что было найдено при старте

Стартовый промпт мастер-плана просит изучить *существующую* структуру
(tenants/organizations, User/Staff/RBAC, Appointment/Schedule) и предложить,
как встроить туда Branch + RBAC v2. На практике репозиторий `Akmalidin/ClinicNet`
на момент старта был **полностью пустым** (ни одного коммита) — исходного
кода SADAF/ODONTIS в нём не было. Это было явно проверено (`git ls-remote`,
GitHub API) и подтверждено пользователем: ClinicNet — чистый старт, стек —
Django + DRF + django-tenants (выбор согласован отдельно, т.к. план явно
ссылается на django-tenants, миграции Django и т.п.).

Соответственно ниже не "план миграции существующих таблиц", а дизайн модели
с нуля, сразу учитывающий Branch + RBAC v2 как часть фундамента, а не как
патч поверх плоской (single-branch) схемы.

## 2. Мультитенантность: тенант = сеть клиник

`apps/tenants` (**public-схема**, `SHARED_APPS`):

* `Client(TenantMixin)` — одна сеть клиник = один Postgres schema
  (`auto_create_schema = True`, схема и миграции создаются автоматически
  при сохранении).
* `Domain(DomainMixin)` — хост → схема (`clinicA.odontis.app` → `clinica`).

Внутри каждой схемы — свои Branch/User/Role/Patient/Appointment, полностью
изолированные от других сетей на уровне Postgres schema (не просто
`tenant_id` фильтром в каждом запросе).

**Осознанное упрощение:** `AUTH_USER_MODEL` (`apps.accounts.User`) живёт
только в `TENANT_APPS`, не в `SHARED_APPS`. Это означает, что в public-схеме
нет таблицы пользователей и нет рабочего Django admin/login — управление
тенантами (создание новой сети) делается через `manage.py create_tenant`
(встроенная команда django-tenants), а не через веб-панель. Причина: если
включить `apps.accounts` в `SHARED_APPS`, `UserRole.branches` (M2M на
`branches.Branch`, который тенант-only) ломает миграцию public-схемы —
Django пытается создать `accounts_userrole_branches` со ссылкой на
несуществующую в public-схеме таблицу `branches_branch`. Платформенная
admin-панель с отдельной моделью пользователя — из будущих фаз, не
блокирует Фазу 1.

## 3. RBAC v2: роль × право × филиал

`apps/accounts`:

* `Permission` — каталог кодов прав (`appointment.view`, `branch.manage`, …).
* `Role` — именованный набор прав (`Врач`, `Администратор филиала`, …).
* `RolePermission` — какие права входят в роль (каталожный уровень,
  без привязки к филиалу).
* `UserRole` — **выдача** роли пользователю, с полем `branch_scope`:
  * `all` — право действует во всех филиалах сети;
  * `own_branch` — право действует только в филиалах, где у пользователя
    есть активный `StaffBranchAssignment` (т.е. он реально там работает);
  * `specific_branches` — право действует только в филиалах из M2M
    `UserRole.branches`.

**Почему `branch_scope` на выдаче роли, а не на самом Permission:** сам код
права (`appointment.view`) — универсален и не должен знать про филиалы.
А вот то, "врачу Иванову дать доступ ко всем филиалам или только к своим" —
это решение про конкретного человека, поэтому живёт на `UserRole`. Так одна
и та же роль "Врач" может быть выдана одному пользователю с `all`
(например, главврач сети), а другому — с `own_branch`.

Единая точка проверки — `apps/accounts/rbac.py`:

* `has_permission(user, code, branch)` — есть ли право `code` у `user`
  в контексте `branch` (`branch=None` = сетевое действие, требует `all`-scope).
* `branches_for_permission(user, code)` — queryset филиалов, где у
  пользователя есть это право (для фильтрации списков).
* `has_any_permission(user, code)` — есть ли право хоть в каком-то scope,
  без привязки к филиалу (для ресурсов, которые сами не привязаны к одному
  филиалу — см. Patient ниже).

Проверка выведена в DRF permission-классы (`apps/accounts/permissions.py`):
`HasBranchPermission` (для ресурсов с обязательным `.branch`) и
`HasPermission` (для ресурсов без него, например `Patient`, у которого
`primary_branch` опционален). Оба класса умеют читать `required_permission`
на вьюсете как строку или как `{"GET": "...", "POST": "..."}`.

**Важный нюанс, найденный вручную (не тестами) при прогоне API через curl:**
первая версия `HasBranchPermission.has_permission` требовала точный branch
context на **любом** списочном запросе — из-за этого пользователь с
`own_branch`-правом получал 403 на банальный `GET /api/v1/branches/` без
`?branch=`, хотя `get_queryset()` и так корректно фильтрует результат по
его филиалам. Исправлено: если branch из запроса не резолвится (обычный
list без фильтра), проверяется "есть ли право хоть в каком-то scope"
(`has_any_permission`), а сам список фильтруется в `get_queryset`. Если
branch передан явно (`?branch=` или в теле запроса) — проверяется именно
этот филиал. Регрессионный тест на этот случай — в
`apps/accounts/tests.py::BranchScopedAPITests`.

## 4. Филиалы и расписание

`apps/branches`:

* `Branch` — название, `code` (slug, уникальный в рамках схемы), адрес,
  IANA timezone, статус (`active | opening | closed`).
* `StaffBranchAssignment` — сотрудник ↔ филиал ↔ день недели ↔ часы смены.
  Это ровно то, что питает `own_branch` RBAC-scope: "свои филиалы" врача —
  это филиалы, где у него есть активная запись здесь, а не что-то отдельно
  настраиваемое.

## 5. Пациенты и приёмы

`apps/patients` — минимальная `Patient` (без полноценной ЭМК — это Фаза 2),
с опциональным `primary_branch` (справочно, не ограничивает видимость
жёстко: пациент без `primary_branch` виден всем с правом `patient.view`).

`apps/scheduling` — `Appointment` с обязательным `branch`, `patient`,
`doctor`, временным интервалом и статусом. `Appointment.clean()`:

* `starts_at < ends_at`;
* **защита от двойной записи врача** — пересечение по времени с любым
  активным (`scheduled/confirmed/in_progress`) приёмом того же врача.
  Важно: проверка **не** ограничена филиалом приёма — врач физически не
  может быть в двух филиалах одновременно, даже если в разных филиалах у
  него разное расписание в разные дни. Это тоже было найдено и исправлено
  в процессе (первая версия ошибочно скоупила overlap-проверку по
  `branch_id`, что разрешало параллельную "запись" в двух филиалах
  одновременно) — см. `apps/scheduling/tests.py::test_cross_branch_overlap_rejected`.

## 6. API

REST (DRF) внутри схемы тенанта, JWT-аутентификация
(`djangorestframework-simplejwt`):

* `POST /api/v1/auth/token/`, `POST /api/v1/auth/token/refresh/`
* `GET /api/v1/me/` — кто я + мои роли/scope
* `/api/v1/roles/`, `/api/v1/permissions/`, `/api/v1/user-roles/`
* `/api/v1/branches/`, `/api/v1/branch-assignments/`
* `/api/v1/patients/`
* `/api/v1/appointments/`

Все списочные эндпоинты, где применимо, фильтруются по видимым
пользователю филиалам через `branches_for_permission` — клиенту не нужно
вручную переключать "контекст филиала", это и есть требование мастер-плана
("расписание в UI фильтруется по филиалу без ручного переключения
контекста").

## 7. Как проверено

* `python manage.py makemigrations --check` — чисто, миграции соответствуют моделям.
* Полный цикл на реальном Postgres 16: `migrate_schemas --shared` →
  `create_tenant` (создаёт новую схему и мигрирует её) → `tenant_command
  seed_rbac` → ручной smoke-test через `tenant_command shell` (два врача,
  один на двух филиалах, другой на одном — проверено, что RBAC и
  `branches_for_permission` фильтруют правильно; проверено, что overlap
  validation работает и в рамках одного филиала, и между филиалами).
* То же самое через реальный HTTP: `runserver` + `curl` с JWT и
  Host-заголовком тенант-домена — включая найденный и исправленный баг
  с 403 на списочных эндпоинтах (см. п. 3).
* Автотесты (`TenantTestCase` из `django-tenants`, реальная Postgres-схема
  на каждый прогон, не sqlite/mock): `apps/accounts/tests.py`,
  `apps/branches/tests.py`, `apps/scheduling/tests.py` — 16 тестов, все
  зелёные (`manage.py test apps`).

## 8. Осознанные ограничения Фазы 1 (не баги, а границы фазы)

* **Нет frontend/UI.** Мастер-план ссылается на `network-dashboard.html` и
  `multi-branch-schedule.html` как визуальный эталон — этих файлов не было
  в репозитории на момент Фазы 1, и построение UI не входило в
  подтверждённый скоуп (Branch + RBAC v2 + мультифилиальное расписание на
  уровне данных/API). API спроектирован так, чтобы такой UI можно было
  построить без дополнительной фильтрации на бэкенде.
* **Нет платформенной admin-панели** для управления тенантами (см. п. 2) —
  провижининг сети через CLI (`manage.py create_tenant`).
* **`Appointment`/`Visit`/`Invoice` backfill-миграция** из мастер-плана
  ("добавить `branch` FK, backfill на единственный текущий филиал") не
  нужна: `Appointment` создан сразу с обязательным `branch`, `Visit` и
  `Invoice` — это Фаза 2/3.
* **Ролей и прав — стартовый каталог** (`manage.py seed_rbac`,
  идемпотентна): `network-admin`, `branch-admin`, `doctor`,
  `receptionist`. Каталог рассчитан на расширение в следующих фазах
  (billing, inventory, referrals и т.д. добавят свои коды прав).

## 9. Следующий шаг

По завершении ревью и деплоя Фазы 1 — переход к Фазе 2 (клинический
контур: единая ЭМК, направления, диагностика) согласно
`docs/ODONTIS-Enterprise-Phased-Plan.md`.
