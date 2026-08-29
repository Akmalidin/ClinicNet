from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import ReferralViewSet

router = DefaultRouter()
router.register("referrals", ReferralViewSet, basename="referral")

urlpatterns = [
    path("", include(router.urls)),
]
