from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import FinanceReportView, InvoiceViewSet, PaymentViewSet

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentViewSet, basename="payment")

urlpatterns = [
    path("finance/report/", FinanceReportView.as_view(), name="finance-report"),
    path("", include(router.urls)),
]
