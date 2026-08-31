from rest_framework import serializers

from .models import BranchPriceOverride, Invoice, InvoiceLine, Payment, Service


class BranchPriceOverrideSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = BranchPriceOverride
        fields = ("id", "service", "branch", "branch_name", "price", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class ServiceSerializer(serializers.ModelSerializer):
    branch_overrides = BranchPriceOverrideSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = ("id", "name", "code", "base_price", "is_active", "branch_overrides", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class InvoiceLineSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True, default=None)

    class Meta:
        model = InvoiceLine
        fields = (
            "id", "service", "service_name", "description", "quantity", "unit_price",
            "line_total", "created_at",
        )
        read_only_fields = ("id", "created_at")


class PaymentSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(source="received_by.__str__", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id", "invoice", "branch", "branch_name", "received_by", "received_by_name",
            "kind", "method", "amount", "note", "received_at",
        )
        # Append-only ledger — every field is read-only here. Creation
        # happens only through InvoiceViewSet.pay(), never a raw POST to
        # this serializer, so there is no writable path that could edit
        # or backdate a payment after the fact.
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.__str__", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    issued_by_name = serializers.CharField(source="issued_by.__str__", read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    # Computed from InvoiceLine/Payment every time (see Invoice's model
    # docstring) — never stored columns, so these can't drift from what
    # the lines/payments actually say.
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    paid_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invoice
        fields = (
            "id",
            "patient", "patient_name",
            "branch", "branch_name",
            "source_visit",
            "issued_by", "issued_by_name",
            "status", "notes",
            "lines", "payments",
            "total_amount", "paid_total", "balance_due", "is_paid",
            "created_at", "updated_at",
        )
        # status only changes through issue/cancel (views.py), never a
        # raw PATCH — same reasoning as Referral.status/LabOrder.status.
        # Lines/payments are likewise managed only through actions
        # (add_line/remove_line/pay), never nested-writable here.
        read_only_fields = ("id", "issued_by", "status", "created_at", "updated_at")
