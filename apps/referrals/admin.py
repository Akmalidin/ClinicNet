from django.contrib import admin

from .models import Referral


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = (
        "patient", "from_doctor", "to_doctor", "to_specialty",
        "from_branch", "to_branch", "status", "priority", "created_at",
    )
    list_filter = ("status", "priority", "from_branch", "to_branch")
    autocomplete_fields = (
        "patient", "from_doctor", "to_doctor", "to_specialty",
        "from_branch", "to_branch", "source_visit", "target_appointment",
        "outcome_visible_to",
    )
    search_fields = ("patient__last_name", "patient__first_name", "reason")
    date_hierarchy = "created_at"
