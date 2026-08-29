from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.rbac import users_with_permission
from apps.notifications.models import Notification

from ...models import Referral, ReferralStatus

STALE_AFTER = timedelta(hours=24)


class Command(BaseCommand):
    """PENDING > 24ч -> уведомление координаторам филиала-получателя
    (ClinicNet-Referrals-Prompt.md section 5). Рассчитано на запуск под
    cron (Celery beat в проекте не поднят — см. docs/PHASE2-REFERRALS-DESIGN.md),
    например раз в час: `manage.py tenant_command escalate_stale_referrals --schema=<...>`.
    """

    help = "Notify branch coordinators about referrals stuck in PENDING for more than 24h."

    def handle(self, *args, **options):
        cutoff = timezone.now() - STALE_AFTER
        stale = Referral.objects.filter(
            status=ReferralStatus.PENDING, created_at__lt=cutoff
        ).select_related("to_branch", "patient")

        notified = 0
        for referral in stale:
            for user in users_with_permission(referral.to_branch, "referrals.manage"):
                already_notified = Notification.objects.filter(
                    recipient=user, referral=referral, title__startswith="Направление ожидает"
                ).exists()
                if already_notified:
                    continue
                Notification.objects.create(
                    recipient=user,
                    referral=referral,
                    title=f"Направление ожидает > 24ч: {referral.patient}",
                    body=referral.reason,
                )
                notified += 1

        self.stdout.write(
            self.style.SUCCESS(f"{stale.count()} stale referral(s), {notified} notification(s) sent.")
        )
