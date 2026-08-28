from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Permission, Role, RolePermission, User, UserRole


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("ODONTIS", {"fields": ("phone", "job_title")}),
    )
    list_display = ("username", "get_full_name", "job_title", "is_active", "is_staff")


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 1


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "codename", "is_system")
    search_fields = ("name", "codename")
    inlines = [RolePermissionInline]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "category", "description")
    list_filter = ("category",)
    search_fields = ("code", "description")


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "branch_scope", "is_active", "granted_at")
    list_filter = ("branch_scope", "is_active", "role")
    autocomplete_fields = ("user", "role", "branches")
    search_fields = ("user__username", "role__name")
