from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Client(TenantMixin):
    """A tenant = one clinic network (organization). Lives in the public schema.

    Everything below this (branches, staff, RBAC, patients, appointments)
    is created inside this tenant's own Postgres schema and is fully
    isolated from every other network.
    """

    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_on = models.DateField(auto_now_add=True)

    # django-tenants: automatically create/drop the Postgres schema for us.
    auto_create_schema = True
    auto_drop_schema = False

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    """Hostname routing table (e.g. clinicA.odontis.app) -> Client schema."""
