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
        ],
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
