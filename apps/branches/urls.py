from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import BranchViewSet, StaffBranchAssignmentViewSet

router = DefaultRouter()
router.register("branches", BranchViewSet, basename="branch")
router.register("branch-assignments", StaffBranchAssignmentViewSet, basename="branch-assignment")

urlpatterns = [
    path("", include(router.urls)),
]
