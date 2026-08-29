from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "title", "referral", "is_read", "created_at")
    list_filter = ("is_read",)
    autocomplete_fields = ("recipient", "referral")
    search_fields = ("recipient__username", "title", "body")
    date_hierarchy = "created_at"
