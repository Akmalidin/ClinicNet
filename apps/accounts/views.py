from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Permission, Role, UserRole
from .serializers import (
    PermissionSerializer,
    RoleSerializer,
    UserRoleSerializer,
    UserSerializer,
)


class MeView(APIView):
    """Who am I, and (for convenience) which branches can I act in per permission."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request):
        user = request.user
        data = UserSerializer(user).data
        data["roles"] = [
            {
                "role": ur.role.name,
                "branch_scope": ur.branch_scope,
                "branches": list(ur.branches.values_list("id", flat=True)),
            }
            for ur in user.user_roles.filter(is_active=True).select_related("role")
        ]
        return Response(data)


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.prefetch_related("permissions").all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated]


class UserRoleViewSet(viewsets.ModelViewSet):
    queryset = UserRole.objects.select_related("user", "role").prefetch_related("branches").all()
    serializer_class = UserRoleSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(granted_by=self.request.user)
