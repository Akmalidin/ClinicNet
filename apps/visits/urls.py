from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import VisitViewSet

router = DefaultRouter()
router.register("visits", VisitViewSet, basename="visit")

urlpatterns = [
    path("", include(router.urls)),
]
