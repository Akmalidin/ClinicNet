from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import PatientViewSet

router = DefaultRouter()
router.register("patients", PatientViewSet, basename="patient")

urlpatterns = [
    path("", include(router.urls)),
]
