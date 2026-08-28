# ClinicNet / ODONTIS Enterprise

Мультитенантная (сеть клиник) backend-платформа на Django + DRF +
[django-tenants](https://django-tenants.readthedocs.io/) (schema-per-tenant
изоляция на уровне Postgres). Разработка ведётся по фазам — см.
[`docs/ODONTIS-Enterprise-Phased-Plan.md`](docs/ODONTIS-Enterprise-Phased-Plan.md).

**Текущая фаза: Фаза 1 — Фундамент** (Branch + RBAC v2 +
мультифилиальное расписание). Дизайн и обоснование решений —
[`docs/PHASE1-DESIGN.md`](docs/PHASE1-DESIGN.md).

## Стек

* Python 3.11+, Django 5.2, Django REST Framework
* django-tenants (мультитенантность через отдельную Postgres-схему на сеть клиник)
* djangorestframework-simplejwt (JWT-аутентификация)
* PostgreSQL 14+

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
  accounts/        # User, RBAC v2 (Role/Permission/UserRole), проверка прав
  branches/        # Branch, StaffBranchAssignment (график по филиалам)
  patients/        # Patient (минимальная карточка, полноценная ЭМК — Фаза 2)
  scheduling/       # Appointment (обязательно привязан к branch)
docs/              # мастер-план по фазам + дизайн-документы фаз
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
