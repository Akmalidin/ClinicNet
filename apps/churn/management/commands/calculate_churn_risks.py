from django.core.management.base import BaseCommand

from apps.churn.services import calculate_churn_risks


class Command(BaseCommand):
    """Пересчёт эвристики оттока пациентов (Фаза 5, под-модуль 1).
    Рассчитано на запуск под cron (Celery beat в проекте не поднят — см.
    docs/PHASE2-REFERRALS-DESIGN.md), тем же паттерном, что
    escalate_stale_referrals, например раз в сутки:
    `manage.py tenant_command calculate_churn_risks --schema=<...>`.
    """

    help = "Recalculate patient churn-risk alerts from visit history (patient-not-back-in-a-while heuristic)."

    def handle(self, *args, **options):
        result = calculate_churn_risks()
        self.stdout.write(
            self.style.SUCCESS(
                "Churn risks: {created} created, {updated} updated, {reactivated} reactivated, "
                "{skipped_degenerate} skipped (no meaningful interval).".format(**result)
            )
        )
