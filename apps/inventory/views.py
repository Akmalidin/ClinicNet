from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasBranchPermission, HasNetworkWidePermission
from apps.accounts.rbac import branches_for_permission

from .models import ZERO, Product, Stock, StockMovement, StockMovementReason
from .serializers import ProductSerializer, StockMovementSerializer, StockSerializer


def _validation_detail(exc: DjangoValidationError):
    return exc.message_dict if hasattr(exc, "message_dict") else exc.messages


class ProductViewSet(viewsets.ModelViewSet):
    """Network-wide consumables catalog. Reads open to any authenticated
    user (same reasoning as ServiceViewSet — knowing "Анестетик Ultracain
    exists in the catalog" isn't sensitive); writes require
    inventory.manage with an ALL-scope grant (HasNetworkWidePermission,
    same shape as pricing.manage/insurance.manage) — editing the catalog
    affects every branch at once.
    """

    serializer_class = ProductSerializer
    permission_classes = [HasNetworkWidePermission]
    required_permission = {
        "POST": "inventory.manage",
        "PUT": "inventory.manage",
        "PATCH": "inventory.manage",
        "DELETE": "inventory.manage",
    }
    filterset_fields = ["is_active"]
    queryset = Product.objects.all()


class StockViewSet(viewsets.ModelViewSet):
    """One branch's tracking of one product — branch-scoped like
    Appointment/Visit/LabOrder/Invoice, via HasBranchPermission.
    inventory.view (read) / inventory.stock.manage (create/adjust) are
    separate, same split as finance.view/manage.
    """

    serializer_class = StockSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "inventory.view",
        "POST": "inventory.stock.manage",
        "PUT": "inventory.stock.manage",
        "PATCH": "inventory.stock.manage",
        "DELETE": "inventory.stock.manage",
    }
    filterset_fields = ["branch", "product"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "inventory.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return Stock.objects.filter(branch__in=allowed_branches).select_related("product", "branch")

    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        """Records one StockMovement against this Stock row — a restock
        (positive quantity_delta) or a manual adjustment in either
        direction (correcting a stocktake, writing off spoilage/damage).
        Consumption tied to closing a Visit goes through
        VisitViewSet.close() instead (apps.inventory.services.
        consume_for_visit) — this is for everything else that changes
        what's actually on the shelf. Same "reject, never silently
        corrupt" guard as consume_for_visit: never lets on-hand go
        negative, whatever the reason.
        """
        stock = self.get_object()
        try:
            quantity_delta = Decimal(str(request.data.get("quantity_delta", "")))
        except (InvalidOperation, TypeError):
            return Response({"detail": "Некорректное количество."}, status=400)
        if quantity_delta == ZERO:
            return Response({"detail": "Движение не может быть нулевым."}, status=400)

        reason = request.data.get("reason", StockMovementReason.ADJUSTMENT)
        if reason not in StockMovementReason.values:
            return Response({"detail": "Некорректная причина движения."}, status=400)

        if stock.on_hand_quantity + quantity_delta < ZERO:
            return Response(
                {"detail": f"Операция увела бы остаток в минус (сейчас {stock.on_hand_quantity})."},
                status=400,
            )

        movement = StockMovement(
            product=stock.product,
            branch=stock.branch,
            quantity_delta=quantity_delta,
            reason=reason,
            created_by=request.user,
            note=request.data.get("note", ""),
        )
        try:
            movement.full_clean()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))
        movement.save()
        return Response(self.get_serializer(stock).data, status=201)

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        """Every Stock row, scoped to this user's branches, currently
        below its own min_quantity — "остаток < минимума" алерт (master
        plan: "это же источник алерта... на дашборде сети"). Derived on
        every call from on_hand_quantity, same as everything else in this
        app — never a separately-maintained "is this low" flag that could
        drift from the movement ledger.
        """
        allowed_branches = branches_for_permission(request.user, "inventory.view")
        stocks = Stock.objects.filter(branch__in=allowed_branches).select_related("product", "branch")
        below = [s for s in stocks if s.is_below_minimum]
        return Response(self.get_serializer(below, many=True).data)


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """The stock ledger, read-only — append-only by design (see
    StockMovement's docstring). Creation only happens through
    StockViewSet.adjust() or apps.inventory.services.consume_for_visit."""

    serializer_class = StockMovementSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {"GET": "inventory.view"}
    filterset_fields = ["branch", "product", "reason", "source_visit"]

    def get_queryset(self):
        allowed_branches = branches_for_permission(self.request.user, "inventory.view")
        return StockMovement.objects.filter(branch__in=allowed_branches).select_related(
            "product", "branch", "created_by", "source_visit"
        )
