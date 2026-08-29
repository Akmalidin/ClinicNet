"""When the receiving doctor closes the calendar record a referral was
scheduled into, close the referral too (ClinicNet-Referrals-Prompt.md
section 5: "Сигнал: при Appointment.status → completed... вызвать
referral.mark_completed()").
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.scheduling.models import Appointment, AppointmentStatus

from .services import notify_referral_completed


@receiver(post_save, sender=Appointment)
def complete_referral_on_appointment_completed(sender, instance, **kwargs):
    if instance.status != AppointmentStatus.COMPLETED:
        return
    # ReverseOneToOneDescriptor.RelatedObjectDoesNotExist subclasses
    # AttributeError, so getattr's default covers "no referral attached".
    referral = getattr(instance, "referral", None)
    if referral is None:
        return
    # mark_completed() itself no-ops (returns False) if the referral is
    # already terminal (COMPLETED or — e.g. it was DECLINED after
    # scheduling but its target_appointment still got closed — DECLINED),
    # so this never re-fires the notification or reopens a closed referral.
    if referral.mark_completed():
        notify_referral_completed(referral)
