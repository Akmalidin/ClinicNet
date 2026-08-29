# ClinicNet

Мультитенантная (сеть клиник) backend-платформа на Django + DRF +
[django-tenants](https://django-tenants.readthedocs.io/) (schema-per-tenant
изоляция на уровне Postgres). Разработка ведётся по фазам — см.
[`docs/ClinicNet-Master-Plan.md`](docs/ClinicNet-Master-Plan.md).

**Фаза 1 — Фундамент** (Branch + RBAC v2 + мультифилиальное расписание) —
готово, дизайн в [`docs/PHASE1-DESIGN.md`](docs/PHASE1-DESIGN.md).

**Текущая фаза: Фаза 2 — Клинический контур** (единая ЭМК + модуль
направлений + базовая диагностика). Бэкенд (модели, API, RBAC, уведомления,
`available-slots`) готов и задеплоен — дизайн в
[`docs/PHASE2-REFERRALS-DESIGN.md`](docs/PHASE2-REFERRALS-DESIGN.md),
спецификация направлений — [`docs/ClinicNet-Referrals-Prompt.md`](docs/ClinicNet-Referrals-Prompt.md).
Frontend направлений — в работе, план в
[`docs/ClinicNet-Phase2-Frontend-Prompt.md`](docs/ClinicNet-Phase2-Frontend-Prompt.md)
(`ReferralModal.vue` для сценария "внутри одного филиала" готов — см.
[`frontend/README.md`](frontend/README.md)). Осталось: кросс-филиальный
сценарий модалки, `ReferralQueueWidget.vue`, `ReferralBadge.vue`, базовая
диагностика.

## Стек

* Python 3.11+, Django 5.2, Django REST Framework
* django-tenants (мультитенантность через отдельную Postgres-схему на сеть клиник)
* djangorestframework-simplejwt (JWT-аутентификация)
* PostgreSQL 14+
* Frontend: Vue 3 + Vite + Pinia + Tailwind (SPA, отдельно от бэкенда — см.
  [`frontend/README.md`](frontend/README.md))

## Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # и поправить под своё окружение при необходимости

# Публичная схема (реестр тенантов)
python manage.py migrate_schemas --shared

# Создать сеть клиник (тенант) + основной домен
python manage.py create_tenant \
  --schema_name=demo_clinic --name="Demo Clinic Network" \
  --domain-domain=demo.localhost --domain-is_primary=True --noinput
# добавьте "127.0.0.1 demo.localhost" в /etc/hosts для локальной разработки

# Стартовый каталог прав + системные роли для этой сети
python manage.py tenant_command seed_rbac --schema=demo_clinic

python manage.py runserver
# запросы к API этой сети — с заголовком Host: demo.localhost
```

## Структура проекта

```
config/            # settings, urls (tenant-схема и public-схема отдельно)
apps/
  tenants/         # Client/Domain — public-схема, реестр сетей клиник
  accounts/        # User, Specialty, RBAC v2 (Role/Permission/UserRole), проверка прав
  branches/        # Branch, StaffBranchAssignment (график по филиалам)
  patients/        # Patient — единая карта пациента, видна на всю сеть
  scheduling/       # Appointment (обязательно привязан к branch)
  visits/          # Visit — клиническая запись приёма (Фаза 2)
  referrals/       # Referral — направления между врачами + API/actions (Фаза 2)
  notifications/   # Notification — внутренний инбокс (без WA/Telegram-провода)
docs/              # мастер-план по фазам + дизайн-документы фаз
frontend/          # Vue 3 SPA — см. frontend/README.md
```

## Тесты

```bash
python manage.py test apps
```

Тесты используют `django_tenants.test.cases.TenantTestCase` — каждый
тестовый класс поднимает отдельную реальную Postgres-схему, а не мокает
БД. Для DRF-запросов внутри теста обязателен заголовок
`HTTP_HOST=<tenant-домен>` (`self.domain.domain` из `TenantTestCase`) —
без него `TenantMainMiddleware` уводит соединение в public-схему.

## RBAC v2 в двух словах

Право (`Permission`, например `appointment.view`) входит в роль
(`Role` через `RolePermission`). Роль выдаётся пользователю (`UserRole`) с
одним из трёх `branch_scope`:

| branch_scope         | Где действует право                                      |
|-----------------------|-----------------------------------------------------------|
| `all`                  | Во всех филиалах сети                                     |
| `own_branch`           | Только в филиалах, где у пользователя есть активный `StaffBranchAssignment` |
| `specific_branches`    | Только в филиалах из `UserRole.branches`                  |

Проверка — `apps.accounts.rbac.has_permission(user, code, branch)` и
`branches_for_permission(user, code)` (для фильтрации списков). Подробности
и найденные при ручном тестировании нюансы — в `docs/PHASE1-DESIGN.md`.
