from django.contrib import admin

from .models import Visit


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "branch", "status", "created_at", "closed_at")
    list_filter = ("branch", "status", "doctor")
    autocomplete_fields = ("patient", "doctor", "branch", "appointment")
    search_fields = ("patient__last_name", "patient__first_name", "doctor__username")
    date_hierarchy = "created_at"
