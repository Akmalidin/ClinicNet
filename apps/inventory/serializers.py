from rest_framework import serializers

from .models import Product, Stock, StockMovement


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ("id", "name", "code", "unit", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.__str__", read_only=True)

    class Meta:
        model = StockMovement
        fields = (
            "id", "product", "product_name", "branch", "branch_name", "quantity_delta",
            "reason", "source_visit", "created_by", "created_by_name", "note", "created_at",
        )
        # Append-only ledger — every field read-only here, same shape as
        # apps.finance.PaymentSerializer. Creation only happens through
        # StockViewSet.adjust() or apps.inventory.services.consume_for_visit
        # (called from VisitViewSet.close()), never a raw POST here.
        read_only_fields = fields


class StockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.unit", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    on_hand_quantity = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_below_minimum = serializers.BooleanField(read_only=True)

    class Meta:
        model = Stock
        fields = (
            "id", "product", "product_name", "product_unit", "branch", "branch_name",
            "min_quantity", "on_hand_quantity", "is_below_minimum", "created_at", "updated_at",
        )
        read_only_fields = ("id", "on_hand_quantity", "is_below_minimum", "created_at", "updated_at")
