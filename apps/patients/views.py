from rest_framework import viewsets

from apps.accounts.permissions import HasPermission

from .models import Patient
from .serializers import PatientSerializer


class PatientViewSet(viewsets.ModelViewSet):
    """Network-wide patient list — the unified EMK (Phase 2).

    Phase 1 filtered this list by `primary_branch`, which meant the patient
    CARD itself disappeared (404 on retrieve, absent from list) for staff
    outside that branch — found during Phase 2 recon as exactly the "карта
    = один филиал" bug the master plan calls out. Fixed: holding
    `patient.view`/`patient.manage` in ANY scope (even own_branch) opens
    the whole network's patient list — a doctor must see a patient's full
    history regardless of which branch they registered at. `primary_branch`
    stays available as an explicit, opt-in filter (`?primary_branch=`, see
    `filterset_fields`), it just no longer silently restricts visibility.
    Branch-scoping still applies, as it should, to what happens *inside*
    the card — Visit/Appointment/Referral querysets filter by branch.
    """

    serializer_class = PatientSerializer
    permission_classes = [HasPermission]
    required_permission = {
        "GET": "patient.view",
        "POST": "patient.manage",
        "PUT": "patient.manage",
        "PATCH": "patient.manage",
        "DELETE": "patient.manage",
    }
    filterset_fields = ["primary_branch"]
    search_fields = ["first_name", "last_name", "phone"]

    def get_queryset(self):
        return Patient.objects.all()
