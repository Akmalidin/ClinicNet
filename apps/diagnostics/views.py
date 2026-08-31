from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission

from .models import LabOrder, LabOrderStatus
from .serializers import LabOrderSerializer, LabResultSerializer


class LabOrderViewSet(viewsets.ModelViewSet):
    """Lab orders, scoped to the branches the current user can act in —
    same pattern as AppointmentViewSet/VisitViewSet (LabOrder is
    branch-tied clinical activity, not network-wide like Patient).
    """

    serializer_class = LabOrderSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "diagnostics.view",
        "POST": "diagnostics.manage",
        "PUT": "diagnostics.manage",
        "PATCH": "diagnostics.manage",
        "DELETE": "diagnostics.manage",
    }
    filterset_fields = ["branch", "patient", "status", "urgency"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "diagnostics.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return (
            LabOrder.objects.filter(branch__in=allowed_branches)
            .select_related("branch", "patient", "ordered_by", "source_visit", "result")
        )

    def perform_create(self, serializer):
        serializer.save(ordered_by=self.request.user)

    @action(detail=True, methods=["post"])
    def result(self, request, pk=None):
        """Ручной ввод результата ответственным сотрудником — closes the
        order (ORDERED -> COMPLETED). 400s (not 500) on a re-submit: the
        OneToOne would otherwise raise IntegrityError on a second result."""
        order = self.get_object()
        if hasattr(order, "result"):
            return Response({"detail": "У этого заказа уже есть результат."}, status=400)
        if order.status == LabOrderStatus.CANCELLED:
            return Response({"detail": "Заказ отменён — результат внести нельзя."}, status=400)

        serializer = LabResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(order=order, entered_by=request.user)

        order.status = LabOrderStatus.COMPLETED
        try:
            order.full_clean()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        order.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(order).data, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if not order.cancel():
            return Response(
                {"detail": "Заказ уже закрыт и не может быть изменён."}, status=400
            )
        return Response(self.get_serializer(order).data)
