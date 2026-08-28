from django.db.models import Q
from rest_framework import viewsets

from apps.accounts.permissions import HasPermission
from apps.accounts.rbac import branches_for_permission

from .models import Patient
from .serializers import PatientSerializer


class PatientViewSet(viewsets.ModelViewSet):
    """Network-wide patient list, filtered to the branches the user can see.

    A patient with no `primary_branch` (not yet tied to one) is visible to
    anyone with the base permission, since it isn't scoped to any branch yet.
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
        code = self.required_permission.get(self.request.method, "patient.view")
        allowed_branches = branches_for_permission(self.request.user, code)
        return Patient.objects.filter(
            Q(primary_branch__in=allowed_branches) | Q(primary_branch__isnull=True)
        )
