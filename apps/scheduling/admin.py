from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "branch", "starts_at", "ends_at", "status")
    list_filter = ("branch", "status", "doctor")
    autocomplete_fields = ("patient", "doctor", "branch")
    search_fields = ("patient__last_name", "patient__first_name", "doctor__username")
    date_hierarchy = "starts_at"
