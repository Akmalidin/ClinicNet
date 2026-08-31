from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import ChurnRiskViewSet

router = DefaultRouter()
router.register("churn-risks", ChurnRiskViewSet, basename="churn-risk")

urlpatterns = [
    path("", include(router.urls)),
]
