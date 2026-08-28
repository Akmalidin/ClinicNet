"""URLs served inside a tenant schema (i.e. for a specific clinic network)."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.branches.urls")),
    path("api/v1/", include("apps.patients.urls")),
    path("api/v1/", include("apps.scheduling.urls")),
]
