from django.contrib import admin

from .models import ChurnRisk


@admin.register(ChurnRisk)
class ChurnRiskAdmin(admin.ModelAdmin):
    list_display = (
        "patient", "branch", "last_visit_date", "avg_interval_days", "days_overdue", "risk_score", "status",
    )
    list_filter = ("branch", "status")
    search_fields = ("patient__first_name", "patient__last_name")
    autocomplete_fields = ("patient", "branch")
    date_hierarchy = "last_visit_date"

    def has_add_permission(self, request):
        # Создаётся только calculate_churn_risks (cron) — не через admin.
        return False
