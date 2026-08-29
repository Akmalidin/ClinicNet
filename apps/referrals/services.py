"""Notification hooks for the Referral lifecycle.

ClinicNet-Referrals-Prompt.md section 5 specifies WhatsApp/Telegram +
"internal inbox" delivery. The provider wiring isn't built yet (see
docs/PHASE2-REFERRALS-DESIGN.md) — these functions write to the internal
inbox only (apps.notifications.Notification). Swap/extend the body here
when a real WA/Telegram sender exists; callers (views.py, signals.py)
don't need to change.
"""
from apps.notifications.models import Notification


def notify_referral_created(referral):
    if not referral.to_doctor_id:
        return  # "на специальность" без конкретного врача — некому слать пока не назначен
    Notification.objects.create(
        recipient_id=referral.to_doctor_id,
        referral=referral,
        title=f"Новое направление: {referral.patient}",
        body=referral.reason,
    )


def notify_referral_declined(referral):
    Notification.objects.create(
        recipient_id=(referral.outcome_visible_to_id or referral.from_doctor_id),
        referral=referral,
        title=f"Направление отклонено: {referral.patient}",
        body=referral.outcome_note,
    )


def notify_referral_completed(referral):
    Notification.objects.create(
        recipient_id=(referral.outcome_visible_to_id or referral.from_doctor_id),
        referral=referral,
        title=f"Направление завершено: {referral.patient}",
        body=referral.outcome_note,
    )
