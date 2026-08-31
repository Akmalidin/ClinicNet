from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import (
    BranchPriceOverrideViewSet,
    FinanceReportView,
    InvoiceViewSet,
    PaymentViewSet,
    ServiceViewSet,
)

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentViewSet, basename="payment")
router.register("services", ServiceViewSet, basename="service")
router.register("price-overrides", BranchPriceOverrideViewSet, basename="price-override")

urlpatterns = [
    path("finance/report/", FinanceReportView.as_view(), name="finance-report"),
    path("", include(router.urls)),
]
