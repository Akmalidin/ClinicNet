from rest_framework.routers import DefaultRouter

from django.urls import include, path

from .views import (
    AdmissionViewSet,
    BedViewSet,
    ClinicalOrderViewSet,
    DepartmentViewSet,
    RoomViewSet,
    StaffDepartmentAssignmentViewSet,
    TransferViewSet,
    VitalsRecordViewSet,
)

router = DefaultRouter()
router.register("departments", DepartmentViewSet, basename="department")
router.register("rooms", RoomViewSet, basename="room")
router.register("beds", BedViewSet, basename="bed")
router.register("department-staff", StaffDepartmentAssignmentViewSet, basename="department-staff")
router.register("admissions", AdmissionViewSet, basename="admission")
router.register("transfers", TransferViewSet, basename="transfer")
router.register("clinical-orders", ClinicalOrderViewSet, basename="clinical-order")
router.register("vitals-records", VitalsRecordViewSet, basename="vitals-record")

urlpatterns = [
    path("", include(router.urls)),
]
