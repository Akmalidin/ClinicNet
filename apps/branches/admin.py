from django.contrib import admin

from .models import Branch, StaffBranchAssignment


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "status", "timezone", "phone")
    list_filter = ("status",)
    search_fields = ("name", "code")


@admin.register(StaffBranchAssignment)
class StaffBranchAssignmentAdmin(admin.ModelAdmin):
    list_display = ("staff", "branch", "weekday", "start_time", "end_time", "is_active")
    list_filter = ("branch", "weekday", "is_active")
    autocomplete_fields = ("staff", "branch")
    search_fields = ("staff__username", "branch__name")
