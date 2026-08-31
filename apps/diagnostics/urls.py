from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import LabOrderViewSet

router = DefaultRouter()
router.register("lab-orders", LabOrderViewSet, basename="lab-order")

urlpatterns = [
    path("", include(router.urls)),
]
