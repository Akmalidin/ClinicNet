from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import (
    BranchPriceOverrideViewSet,
    FinanceReportView,
    InsurancePolicyViewSet,
    InsuranceProviderViewSet,
    InvoiceViewSet,
    PaymentViewSet,
    ServiceViewSet,
)

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentViewSet, basename="payment")
router.register("services", ServiceViewSet, basename="service")
router.register("price-overrides", BranchPriceOverrideViewSet, basename="price-override")
router.register("insurance-providers", InsuranceProviderViewSet, basename="insurance-provider")
router.register("insurance-policies", InsurancePolicyViewSet, basename="insurance-policy")

urlpatterns = [
    path("finance/report/", FinanceReportView.as_view(), name="finance-report"),
    path("", include(router.urls)),
]
