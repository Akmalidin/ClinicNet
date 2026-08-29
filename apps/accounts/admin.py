from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Permission, Role, RolePermission, Specialty, User, UserRole


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("ClinicNet", {"fields": ("phone", "job_title", "specialties")}),
    )
    filter_horizontal = DjangoUserAdmin.filter_horizontal + ("specialties",)
    list_display = ("username", "get_full_name", "job_title", "is_active", "is_staff")
    search_fields = DjangoUserAdmin.search_fields + ("phone",)


@admin.register(Specialty)
class SpecialtyAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


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
