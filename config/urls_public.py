"""URLs served from the public schema.

Phase 1 has no web UI here on purpose: tenant provisioning is a platform
operation done via `manage.py create_tenant`, and there is no shared
Django admin/login in the public schema (see settings.SHARED_APPS).
"""
urlpatterns = []
