from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import (
    AdmissionViewSet,
    BedViewSet,
    DepartmentViewSet,
    RoomViewSet,
    StaffDepartmentAssignmentViewSet,
)

router = DefaultRouter()
router.register("departments", DepartmentViewSet, basename="department")
router.register("rooms", RoomViewSet, basename="room")
router.register("beds", BedViewSet, basename="bed")
router.register("department-staff", StaffDepartmentAssignmentViewSet, basename="department-staff")
router.register("admissions", AdmissionViewSet, basename="admission")

urlpatterns = [
    path("", include(router.urls)),
]
