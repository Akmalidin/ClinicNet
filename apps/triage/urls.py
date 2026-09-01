from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import TriageSuggestionViewSet

router = DefaultRouter()
router.register("triage-suggestions", TriageSuggestionViewSet, basename="triage-suggestion")

urlpatterns = [
    path("", include(router.urls)),
]
