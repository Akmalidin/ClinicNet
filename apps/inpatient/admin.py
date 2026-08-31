from django.contrib import admin

from .models import Admission, Bed, Department, Room, StaffDepartmentAssignment, Transfer


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "code", "is_active")
    list_filter = ("branch", "is_active")
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "is_active")
    list_filter = ("department__branch", "department")
    search_fields = ("name",)
    autocomplete_fields = ("department",)


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ("label", "room", "status")
    list_filter = ("status", "room__department__branch")
    search_fields = ("label",)
    autocomplete_fields = ("room",)


@admin.register(StaffDepartmentAssignment)
class StaffDepartmentAssignmentAdmin(admin.ModelAdmin):
    list_display = ("staff", "department", "is_active", "created_at")
    list_filter = ("department__branch", "is_active")
    autocomplete_fields = ("staff", "department")


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ("patient", "department", "bed", "attending_doctor", "status", "admitted_at")
    list_filter = ("department__branch", "department", "status")
    search_fields = ("patient__first_name", "patient__last_name")
    autocomplete_fields = ("patient", "department", "bed", "attending_doctor", "admitted_by")
    date_hierarchy = "admitted_at"


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ("admission", "from_department", "to_department", "transferred_by", "transferred_at")
    list_filter = ("from_department__branch", "from_department", "to_department")
    autocomplete_fields = ("admission", "from_department", "from_bed", "to_department", "to_bed", "transferred_by")
    date_hierarchy = "transferred_at"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
