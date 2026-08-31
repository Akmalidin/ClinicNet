from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Permission, Role, RolePermission

# Phase 1 permission catalog. Later phases (billing, inventory, referrals,
# ...) add their own codes here — this command stays idempotent so it's
# safe to re-run after adding new ones.
PERMISSIONS = [
    ("branch.view", "branches", "Просмотр филиалов"),
    ("branch.manage", "branches", "Создание/редактирование филиалов"),
    ("branch.schedule.view", "branches", "Просмотр графика работы сотрудников"),
    ("branch.schedule.manage", "branches", "Редактирование графика работы сотрудников"),
    ("patient.view", "patients", "Просмотр карточек пациентов"),
    ("patient.manage", "patients", "Создание/редактирование пациентов"),
    ("appointment.view", "scheduling", "Просмотр приёмов"),
    ("appointment.manage", "scheduling", "Создание/редактирование приёмов"),
    ("visit.view", "visits", "Просмотр приёмов (клинических записей)"),
    ("visit.manage", "visits", "Создание/редактирование приёмов (клинических записей)"),
    ("referrals.view", "referrals", "Просмотр направлений"),
    ("referrals.manage", "referrals", "Создание/обработка направлений (schedule/decline/reassign)"),
    ("diagnostics.view", "diagnostics", "Просмотр заказов анализов и результатов"),
    ("diagnostics.manage", "diagnostics", "Заказ анализа, ввод результата, отмена заказа"),
    ("finance.view", "finance", "Просмотр счетов, платежей и отчёта по кассе"),
    ("finance.manage", "finance", "Выставление счетов, приём платежей и возвраты"),
    ("pricing.manage", "finance", "Управление сетевым прайс-листом (каталог услуг)"),
    ("pricing.override", "finance", "Переопределение цены услуги для своего филиала"),
    ("insurance.manage", "finance", "Управление каталогом страховых компаний"),
    ("insurance.view", "finance", "Просмотр полисов пациентов"),
    ("insurance.policy.manage", "finance", "Создание/редактирование полисов пациентов"),
    ("inventory.manage", "inventory", "Управление сетевым каталогом расходников"),
    ("inventory.view", "inventory", "Просмотр остатков и движений склада филиала"),
    ("inventory.stock.manage", "inventory", "Приход/списание/корректировка остатков филиала"),
    ("inpatient.department.view", "inpatient", "Просмотр отделений, палат и коечного фонда"),
    ("inpatient.department.manage", "inpatient", "Создание/редактирование отделений, палат и коек"),
    ("inpatient.admission.view", "inpatient", "Просмотр госпитализаций своего отделения/филиала"),
    ("inpatient.admission.manage", "inpatient", "Госпитализация, выписка своего отделения/филиала"),
    ("inpatient.order.view", "inpatient", "Просмотр назначений своего отделения/филиала"),
    ("inpatient.order.manage", "inpatient", "Назначение/отмена назначения (медикамент/процедура/диета)"),
    ("inpatient.order.perform", "inpatient", "Отметка о выполнении назначения (постовая медсестра)"),
    ("inpatient.vitals.view", "inpatient", "Просмотр листа наблюдения своего отделения/филиала"),
    ("inpatient.vitals.manage", "inpatient", "Добавление замера в лист наблюдения"),
    ("inpatient.operation.view", "inpatient", "Просмотр операций своего отделения/филиала"),
    ("inpatient.operation.manage", "inpatient", "Планирование/отмена/завершение операции"),
    ("inpatient.operation.checklist", "inpatient", "Подтверждение этапов чек-листа безопасности хирургии"),
]

# codename -> (name, is_system, branch-agnostic description, permission codes)
ROLES = {
    "network-admin": {
        "name": "Администратор сети",
        "is_system": True,
        "permissions": [code for code, _, _ in PERMISSIONS],
    },
    "branch-admin": {
        "name": "Администратор филиала",
        "is_system": True,
        "permissions": [
            "branch.view",
            "branch.schedule.view",
            "branch.schedule.manage",
            "patient.view",
            "patient.manage",
            "appointment.view",
            "appointment.manage",
            "visit.view",
            "visit.manage",
            "referrals.view",
            "referrals.manage",
            "diagnostics.view",
            "diagnostics.manage",
            "finance.view",
            "finance.manage",
            # pricing.manage (the network-wide Service catalog) NOT granted
            # here even though branch-admin holds most other .manage codes
            # — it requires an ALL-scope grant specifically (see
            # HasNetworkWidePermission), which UserRole assignment, not
            # this role definition, controls. pricing.override (their own
            # branch's price exceptions) is the branch-level equivalent.
            "pricing.override",
            "insurance.view",
            "insurance.policy.manage",
            # inventory.manage (the network-wide Product catalog) NOT
            # granted here, same reasoning as pricing.manage above —
            # requires an ALL-scope grant specifically. inventory.stock.manage
            # (their own branch's stock — restock/adjust) is the
            # branch-level equivalent, same shape as pricing.override.
            "inventory.view",
            "inventory.stock.manage",
            # inpatient.department.manage (коечный фонд филиала — создание
            # отделений/палат/коек) выдаётся здесь, в отличие от
            # pricing.manage/insurance.manage/inventory.manage — это НЕ
            # сетевой каталог, а структура конкретного филиала (см.
            # apps.inpatient.models.Department), поэтому own_branch-скоуп
            # тут корректен, ALL-scope не требуется.
            "inpatient.department.view",
            "inpatient.department.manage",
            # inpatient.admission.manage — филиальный админ видит и ведёт
            # госпитализации по всем отделениям СВОЕГО филиала (тот же
            # принцип, что finance.manage/visit.manage): own_branch-грант
            # здесь не сужается по отделениям — см. apps.inpatient.rbac.
            "inpatient.admission.view",
            "inpatient.admission.manage",
            "inpatient.order.view",
            "inpatient.order.manage",
            "inpatient.order.perform",
            "inpatient.vitals.view",
            "inpatient.vitals.manage",
            "inpatient.operation.view",
            "inpatient.operation.manage",
            "inpatient.operation.checklist",
        ],
    },
    "doctor": {
        "name": "Врач",
        "is_system": True,
        "permissions": [
            "branch.view",
            "branch.schedule.view",
            "patient.view",
            "appointment.view",
            "appointment.manage",
            "visit.view",
            "visit.manage",
            "diagnostics.view",
            "diagnostics.manage",
            # Read-only — checking "do we have enough anesthetic" before
            # closing a visit with consumed_items. Doesn't need
            # inventory.stock.manage: consuming stock at visit-close time
            # flows from visit.manage (already theirs), not a separate
            # inventory grant — see VisitViewSet.close().
            "inventory.view",
            # Лечащий врач стационара — own_branch-грант даёт видимость по
            # ВСЕМ отделениям своего филиала, не только "своему" (в
            # отличие от медсестры/зав. отделением ниже) — этот проект
            # не моделирует "врач приписан к одному отделению", см.
            # apps.inpatient.rbac.departments_for_permission.
            "inpatient.department.view",
            "inpatient.admission.view",
            "inpatient.admission.manage",
            # Врач и назначает (order.manage), и может отметить
            # выполнение сам (order.perform) — реальный процесс
            # стационара: врач-хирург, к примеру, часто сам выполняет
            # назначенную им же процедуру.
            "inpatient.order.view",
            "inpatient.order.manage",
            "inpatient.order.perform",
            "inpatient.vitals.view",
            "inpatient.vitals.manage",
            "inpatient.operation.view",
            "inpatient.operation.manage",
            "inpatient.operation.checklist",
            # referrals.view/manage НЕ выдаются врачу намеренно: это права
            # координатора/сети на очередь ЦЕЛОГО филиала (own_branch-scope
            # тут означало бы "видит весь список направлений своего
            # филиала", а не только своё — ровно баг, найденный при ручной
            # проверке RBAC-чек-листа). "Своё" (отправил/получил) доступно
            # любому врачу без всякого гранта — см. HasReferralPermission.
        ],
    },
    "receptionist": {
        "name": "Администратор ресепшн",
        "is_system": True,
        "permissions": [
            "branch.view",
            "patient.view",
            "patient.manage",
            "appointment.view",
            "appointment.manage",
            # Видит очередь направлений на ресепшене, но не создаёт/не обрабатывает
            # (schedule/decline/reassign — решение врача или координатора филиала)
            # и не пишет клинические заметки (visit.* нет намеренно).
            "referrals.view",
            # Front-desk intake is where a patient's insurance info
            # actually gets collected — same reasoning as patient.manage
            # already being theirs.
            "insurance.view",
            "insurance.policy.manage",
        ],
    },
    "cashier": {
        "name": "Кассир",
        "is_system": True,
        "permissions": [
            "branch.view",
            # Needs to look up whose invoice they're processing, not to
            # manage patient records — patient.view only, no patient.manage.
            "patient.view",
            "finance.view",
            "finance.manage",
            # Needs to see a patient's policy to bill against it, but
            # doesn't create/edit policies — that's reception/admin's job.
            "insurance.view",
        ],
    },
    "department-head": {
        "name": "Заведующий отделением",
        "is_system": True,
        "permissions": [
            "branch.view",
            "patient.view",
            "inpatient.department.view",
            "inpatient.admission.view",
            "inpatient.admission.manage",
            "inpatient.order.view",
            "inpatient.order.manage",
            "inpatient.order.perform",
            "inpatient.vitals.view",
            "inpatient.vitals.manage",
            "inpatient.operation.view",
            "inpatient.operation.manage",
            "inpatient.operation.checklist",
        ],
        # Department-scoped, NOT branch-scoped: provision this role's
        # UserRole with branch_scope=SPECIFIC_BRANCHES and NO branches
        # attached — that already resolves to "reaches no branches" via
        # apps.accounts.rbac.branches_for_permission, so the ONLY source
        # of visible departments becomes StaffDepartmentAssignment (see
        # apps.inpatient.rbac.departments_for_permission's docstring for
        # why this is deliberate, not a workaround).
    },
    "nurse": {
        "name": "Постовая медсестра",
        "is_system": True,
        "permissions": [
            "branch.view",
            "patient.view",
            "inpatient.admission.view",
            "inpatient.order.view",
            # Выполняет назначения врача, сама не назначает — order.manage
            # (создание/отмена) НЕ выдаётся намеренно, только order.perform.
            "inpatient.order.perform",
            # Лист наблюдения — рутинная работа постового поста, отсюда
            # оба права сразу (в отличие от order.*, где нет симметрии
            # "назначил/выполнил" — замер один и тот же человек и вносит,
            # и видит).
            "inpatient.vitals.view",
            "inpatient.vitals.manage",
            "inpatient.operation.view",
            # Операционная медсестра подтверждает этапы чек-листа
            # (в кабинете, вместе с хирургом/анестезиологом) — та же
            # логика, что order.perform: выполняет, не планирует.
            # operation.manage (планирование/отмена/завершение операции)
            # НЕ выдаётся намеренно.
            "inpatient.operation.checklist",
        ],
        # Same department-scoped provisioning note as "department-head"
        # above — SPECIFIC_BRANCHES with no branches, real reach comes
        # from StaffDepartmentAssignment. inpatient.admission.manage
        # (admit/discharge) is deliberately NOT granted — that's a
        # doctor/department-head decision.
    },
}


class Command(BaseCommand):
    help = "Seed the Phase 1 RBAC permission catalog and default system roles for the current tenant schema."

    @transaction.atomic
    def handle(self, *args, **options):
        for code, category, description in PERMISSIONS:
            perm, created = Permission.objects.update_or_create(
                code=code, defaults={"category": category, "description": description}
            )
            self.stdout.write(f"{'created' if created else 'ok'}: permission {perm.code}")

        for codename, spec in ROLES.items():
            role, created = Role.objects.update_or_create(
                codename=codename, defaults={"name": spec["name"], "is_system": spec["is_system"]}
            )
            self.stdout.write(f"{'created' if created else 'ok'}: role {role.codename}")
            wanted = Permission.objects.filter(code__in=spec["permissions"])
            RolePermission.objects.filter(role=role).exclude(permission__in=wanted).delete()
            for perm in wanted:
                RolePermission.objects.get_or_create(role=role, permission=perm)

        self.stdout.write(self.style.SUCCESS("RBAC catalog seeded."))
