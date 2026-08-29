from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import BranchDirectoryView, BranchViewSet, StaffBranchAssignmentViewSet

router = DefaultRouter()
router.register("branches", BranchViewSet, basename="branch")
router.register("branch-assignments", StaffBranchAssignmentViewSet, basename="branch-assignment")

urlpatterns = [
    # Must come before the router include — otherwise DRF's router would
    # try to match "directory" as a branches/<pk> lookup first.
    path("branches/directory/", BranchDirectoryView.as_view(), name="branch-directory"),
    path("", include(router.urls)),
]
