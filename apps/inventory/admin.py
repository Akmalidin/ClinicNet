from django.contrib import admin

from .models import Product, Stock, StockMovement


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "unit", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("product", "branch", "min_quantity", "on_hand_quantity_display")
    list_filter = ("branch",)
    autocomplete_fields = ("product", "branch")
    search_fields = ("product__name",)

    @admin.display(description="На складе")
    def on_hand_quantity_display(self, obj):
        return obj.on_hand_quantity


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product", "branch", "quantity_delta", "reason", "created_by", "created_at")
    list_filter = ("branch", "reason")
    autocomplete_fields = ("product", "branch", "source_visit", "created_by")
    date_hierarchy = "created_at"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
