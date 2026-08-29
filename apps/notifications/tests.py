from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User

from .models import Notification


class NotificationInboxTests(TenantTestCase):
    """Each user's inbox is their own — never anyone else's (see
    NotificationViewSet.get_queryset)."""

    def setUp(self):
        self.user = User.objects.create(username="doc1")
        self.other_user = User.objects.create(username="doc2")
        self.mine = Notification.objects.create(recipient=self.user, title="Для меня")
        self.not_mine = Notification.objects.create(recipient=self.other_user, title="Не для меня")

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.user)
        self.host = self.domain.domain

    def test_list_only_shows_own_notifications(self):
        response = self.client_api.get("/api/v1/notifications/", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()}
        self.assertEqual(ids, {self.mine.pk})

    def test_cannot_retrieve_someone_elses_notification(self):
        response = self.client_api.get(
            f"/api/v1/notifications/{self.not_mine.pk}/", HTTP_HOST=self.host
        )
        self.assertEqual(response.status_code, 404)

    def test_mark_as_read(self):
        response = self.client_api.patch(
            f"/api/v1/notifications/{self.mine.pk}/", {"is_read": True}, HTTP_HOST=self.host
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.mine.refresh_from_db()
        self.assertTrue(self.mine.is_read)

    def test_title_is_not_writable(self):
        response = self.client_api.patch(
            f"/api/v1/notifications/{self.mine.pk}/",
            {"title": "Подменённый заголовок"},
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.title, "Для меня")  # read_only field, silently ignored
