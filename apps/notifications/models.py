from django.db import models


class Notification(models.Model):
    """Internal "who needs to see what" inbox.

    ClinicNet-Referrals-Prompt.md section 5 asks for WhatsApp/Telegram
    delivery for notify_referral_created/notify_referral_completed. That
    provider wiring is deliberately NOT built in this phase (no such
    service existed before Phase 2 — see docs/PHASE2-REFERRALS-DESIGN.md);
    this model is the inbox those channels will eventually deliver from,
    and is enough on its own for the in-app "у меня есть направление"
    experience right now.
    """

    recipient = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="notifications"
    )
    referral = models.ForeignKey(
        "referrals.Referral",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self):
        return f"{self.recipient}: {self.title}"
