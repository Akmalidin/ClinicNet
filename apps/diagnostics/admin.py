from django.contrib import admin

from .models import LabOrder, LabResult


class LabResultInline(admin.StackedInline):
    model = LabResult
    extra = 0
    autocomplete_fields = ("entered_by",)


@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = ("patient", "test_type", "branch", "urgency", "status", "created_at")
    list_filter = ("branch", "status", "urgency")
    autocomplete_fields = ("patient", "ordered_by", "branch", "source_visit")
    search_fields = ("patient__last_name", "patient__first_name", "test_type")
    date_hierarchy = "created_at"
    inlines = [LabResultInline]
