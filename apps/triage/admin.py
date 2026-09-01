from django.contrib import admin

from .models import TriageSuggestion


@admin.register(TriageSuggestion)
class TriageSuggestionAdmin(admin.ModelAdmin):
    list_display = (
        "contact_name", "channel", "matched_specialty", "branch", "suggested_doctor",
        "suggested_starts_at", "status",
    )
    list_filter = ("branch", "status", "channel")
    search_fields = ("contact_name", "contact_phone", "external_chat_id", "symptom_text")
    autocomplete_fields = ("matched_specialty", "branch", "suggested_doctor", "patient", "confirmed_by")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        # Создаётся только через ingest-API (сервисный аккаунт бота).
        return False
