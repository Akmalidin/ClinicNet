from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .models import Stock, StockMovement, StockMovementReason

ZERO = Decimal("0")


def consume_for_visit(visit, items, user):
    """Records one CONSUMPTION StockMovement per {"product": id,
    "quantity": ...} pair in `items` — called from
    apps.visits.views.VisitViewSet.close() when a doctor records which
    consumables a visit used, closing the loop the master plan asked for:
    "списание расходника при закрытии Visit" (Phase 3 step (d)).

    All-or-nothing: every item is validated (a Stock row exists for that
    product at the visit's branch, the quantity is positive, and
    consuming it wouldn't take on-hand quantity negative) BEFORE any
    movement is created, so one bad item in the list can't leave a
    partial write behind — either the whole visit's consumption is
    recorded, or none of it. Returns [] without touching anything if
    `items` is empty (visits with no billable consumables are normal).
    """
    if not items:
        return []

    resolved = []
    for item in items:
        product_id = item.get("product")
        try:
            quantity = Decimal(str(item.get("quantity", "")))
        except (InvalidOperation, TypeError):
            raise ValidationError(f"Некорректное количество для продукта (id={product_id}).")
        if quantity <= ZERO:
            raise ValidationError(f"Количество должно быть положительным (продукт id={product_id}).")

        stock = (
            Stock.objects.filter(product_id=product_id, branch=visit.branch)
            .select_related("product")
            .first()
        )
        if not stock:
            raise ValidationError(
                f"Филиал «{visit.branch}» не ведёт учёт этого продукта (id={product_id}) — "
                "сначала заведите Stock для него."
            )
        if stock.on_hand_quantity < quantity:
            raise ValidationError(
                f"Недостаточно «{stock.product.name}» на складе филиала «{visit.branch}»: "
                f"есть {stock.on_hand_quantity}, требуется {quantity}."
            )
        resolved.append((stock, quantity))

    return [
        StockMovement.objects.create(
            product=stock.product,
            branch=visit.branch,
            quantity_delta=-quantity,
            reason=StockMovementReason.CONSUMPTION,
            source_visit=visit,
            created_by=user,
        )
        for stock, quantity in resolved
    ]
