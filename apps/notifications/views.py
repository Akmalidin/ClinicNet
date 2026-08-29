from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Each user's own inbox — never anyone else's, no RBAC permission code
    needed beyond being logged in. Only `is_read` is writable (see
    NotificationSerializer) — notifications are system-generated.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["is_read", "referral"]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)
