from django.contrib import admin

from .models import Invoice, InvoiceLine, Payment


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("kind", "method", "amount", "received_by", "note", "received_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Append-only ledger — no editing/adding payments through the
        # admin either, only through InvoiceViewSet.pay(). Visible here
        # for read-only auditing.
        return False


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "branch", "status", "created_at")
    list_filter = ("branch", "status")
    autocomplete_fields = ("patient", "branch", "source_visit", "issued_by")
    search_fields = ("patient__last_name", "patient__first_name")
    date_hierarchy = "created_at"
    inlines = [InvoiceLineInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "invoice", "branch", "kind", "amount", "received_by", "received_at")
    list_filter = ("branch", "kind", "method")
    autocomplete_fields = ("invoice", "branch", "received_by")
    date_hierarchy = "received_at"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
