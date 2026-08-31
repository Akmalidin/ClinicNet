from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from rest_framework import generics
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import HasBranchPermission
from apps.accounts.rbac import branches_for_permission

from .models import ZERO, Invoice, InvoiceLine, InvoiceStatus, Payment, PaymentKind
from .serializers import InvoiceSerializer, PaymentSerializer


def _validation_detail(exc: DjangoValidationError):
    return exc.message_dict if hasattr(exc, "message_dict") else exc.messages


class InvoiceViewSet(viewsets.ModelViewSet):
    """Invoices, scoped to the branches the current user can act in for
    finance.* — same branch-scoping pattern as Appointment/Visit/LabOrder
    (a cash register belongs to one branch, per the master plan).

    Line items and payments are managed entirely through actions here
    (add_line/remove_line/issue/cancel/pay), not separate nested
    resources: every one of them needs the invoice's own branch checked,
    which self.get_object() + HasBranchPermission.has_object_permission
    already does correctly, without having to resolve branch through a
    join the way a standalone InvoiceLine/Payment-create endpoint would.
    """

    serializer_class = InvoiceSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {
        "GET": "finance.view",
        "POST": "finance.manage",
        "PUT": "finance.manage",
        "PATCH": "finance.manage",
        "DELETE": "finance.manage",
    }
    filterset_fields = ["branch", "patient", "status"]

    def get_queryset(self):
        code = self.required_permission.get(self.request.method, "finance.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return (
            Invoice.objects.filter(branch__in=allowed_branches)
            .select_related("branch", "patient", "issued_by", "source_visit")
            .prefetch_related("lines", "payments")
        )

    def perform_create(self, serializer):
        serializer.save(issued_by=self.request.user)

    @action(detail=True, methods=["post"])
    def add_line(self, request, pk=None):
        """Only while DRAFT — InvoiceLine.clean() enforces this too, this
        is just the friendlier 400 before hitting that guard."""
        invoice = self.get_object()
        description = (request.data.get("description") or "").strip()
        unit_price = request.data.get("unit_price")
        if not description or unit_price is None:
            return Response({"detail": "Укажите описание и цену позиции."}, status=400)

        line = InvoiceLine(
            invoice=invoice,
            description=description,
            quantity=request.data.get("quantity", 1),
            unit_price=unit_price,
        )
        try:
            line.full_clean()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))
        line.save()
        # get_object() above prefetched lines/payments via get_queryset()
        # BEFORE this new line existed — without clearing that cache, the
        # response would serialize the stale (pre-creation) prefetch,
        # showing the correct total_amount (that property re-aggregates)
        # next to an empty/stale `lines` array. Caught by actually running
        # this against a live server, not from reading the code.
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data, status=201)

    @action(detail=True, methods=["post"])
    def remove_line(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status != InvoiceStatus.DRAFT:
            return Response(
                {"detail": "Позиции можно удалять только пока счёт в статусе «Черновик»."},
                status=400,
            )
        line = invoice.lines.filter(pk=request.data.get("line_id")).first()
        if not line:
            return Response({"detail": "Позиция не найдена в этом счёте."}, status=404)
        line.delete()
        invoice.refresh_from_db()  # see add_line's comment on stale prefetch
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        invoice = self.get_object()
        try:
            issued = invoice.issue()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))
        if not issued:
            return Response({"detail": "Счёт уже выставлен или закрыт."}, status=400)
        invoice.refresh_from_db()  # see add_line's comment on stale prefetch
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        invoice = self.get_object()
        try:
            cancelled = invoice.cancel()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))
        if not cancelled:
            return Response({"detail": "Счёт уже закрыт."}, status=400)
        invoice.refresh_from_db()  # see add_line's comment on stale prefetch
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Records one Payment (kind=payment or refund) — append-only:
        this never edits or replaces an existing row (see Payment's
        docstring). Rejects, with a 400 rather than a silent duplicate or
        overwrite: a payment on a non-ISSUED invoice, a payment on an
        already-fully-paid invoice, a payment larger than the remaining
        balance, and a refund larger than what's actually been paid."""
        invoice = self.get_object()
        if invoice.status != InvoiceStatus.ISSUED:
            return Response(
                {"detail": "Платежи принимаются только по выставленному счёту."}, status=400
            )

        kind = request.data.get("kind", PaymentKind.PAYMENT)
        try:
            amount = Decimal(str(request.data.get("amount", "")))
        except (InvalidOperation, TypeError):
            return Response({"detail": "Некорректная сумма."}, status=400)

        if kind == PaymentKind.PAYMENT:
            if invoice.balance_due <= ZERO:
                return Response({"detail": "Счёт уже полностью оплачен."}, status=400)
            if amount > invoice.balance_due:
                return Response(
                    {"detail": f"Сумма больше остатка к оплате ({invoice.balance_due})."},
                    status=400,
                )
        elif kind == PaymentKind.REFUND:
            if amount > invoice.paid_total:
                return Response(
                    {"detail": f"Сумма возврата больше уже оплаченного ({invoice.paid_total})."},
                    status=400,
                )

        payment = Payment(
            invoice=invoice,
            branch=invoice.branch,
            received_by=request.user,
            kind=kind,
            method=request.data.get("method", "cash"),
            amount=amount,
            note=request.data.get("note", ""),
        )
        try:
            payment.full_clean()
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(_validation_detail(exc))
        payment.save()
        invoice.refresh_from_db()  # see add_line's comment on stale prefetch
        return Response(self.get_serializer(invoice).data, status=201)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """The payment ledger, read-only — append-only by design (see
    Payment's docstring). Creation only happens through
    InvoiceViewSet.pay(); there is no create/update/destroy here at all."""

    serializer_class = PaymentSerializer
    permission_classes = [HasBranchPermission]
    required_permission = {"GET": "finance.view"}
    filterset_fields = ["branch", "invoice", "kind", "method"]

    def get_queryset(self):
        allowed_branches = branches_for_permission(self.request.user, "finance.view")
        return Payment.objects.filter(branch__in=allowed_branches).select_related(
            "branch", "invoice", "received_by"
        )


class FinanceReportView(generics.GenericAPIView):
    """Consolidated network report — per-branch payment/refund totals for
    an optional date range. Scoped to exactly the branches this user
    holds finance.view in: an own_branch cashier only ever sees their own
    branch's row, a network-admin sees every branch's row separately
    (never one blended network number hiding which branch it came from).
    Queries Payment directly, the same reconciliation principle as
    Invoice's own computed properties — no cached total anywhere.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        allowed_branches = branches_for_permission(request.user, "finance.view")
        qs = Payment.objects.filter(branch__in=allowed_branches)

        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(received_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(received_at__date__lte=date_to)

        by_branch = list(
            qs.values("branch", "branch__name")
            .annotate(
                payments=Coalesce(Sum("amount", filter=Q(kind=PaymentKind.PAYMENT)), ZERO),
                refunds=Coalesce(Sum("amount", filter=Q(kind=PaymentKind.REFUND)), ZERO),
            )
            .order_by("branch__name")
        )
        for row in by_branch:
            row["branch_id"] = row.pop("branch")
            row["branch_name"] = row.pop("branch__name")
            row["net"] = row["payments"] - row["refunds"]

        network_total = sum((row["net"] for row in by_branch), ZERO)
        return Response({"by_branch": by_branch, "network_total": network_total})
