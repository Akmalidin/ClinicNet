"""
Django settings for the ODONTIS Enterprise project.

Phase 1 foundation: multi-tenant (network of clinics) via django-tenants,
with a Branch entity and a branch-aware RBAC layer inside each tenant schema.
See docs/PHASE1-DESIGN.md for the design rationale.
"""
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-insecure-secret-key")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# ---------------------------------------------------------------------------
# django-tenants: SHARED_APPS live in the public schema (one row per clinic
# network / organization). TENANT_APPS are created fresh in every tenant's
# own Postgres schema, so each clinic network's staff, roles, branches,
# patients and appointments are fully isolated from every other network.
# ---------------------------------------------------------------------------
SHARED_APPS = [
    "django_tenants",
    "apps.tenants",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    # NOTE: AUTH_USER_MODEL (apps.accounts.User) is intentionally NOT
    # shared. Every clinic network's staff, roles and RBAC grants live only
    # inside that network's own tenant schema — there is no cross-tenant
    # login. Provisioning a new network (creating its schema + domain) is a
    # platform operation done via `manage.py create_tenant`, not through
    # Django admin in the public schema. A platform-admin panel with its
    # own auth is future work, tracked separately from this RBAC model.
]

TENANT_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.admin",
    "django.contrib.messages",
    "rest_framework",
    "django_filters",
    "apps.accounts",
    "apps.branches",
    "apps.patients",
    "apps.scheduling",
    "apps.visits",
    "apps.referrals",
    "apps.notifications",
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

TENANT_MODEL = "tenants.Client"
TENANT_DOMAIN_MODEL = "tenants.Domain"

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    # Must be first — sets the DB connection's schema before any other
    # middleware (sessions, auth) touches the database.
    "django_tenants.middleware.main.TenantMainMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
PUBLIC_SCHEMA_URLCONF = "config.urls_public"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": config("DB_NAME", default="odontis"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default="postgres"),
        "HOST": config("DB_HOST", default="127.0.0.1"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# nginx terminates TLS and forwards this header — without it Django can't
# tell the request was HTTPS (matters for SECURE_SSL_REDIRECT below and
# for building https:// links).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
    ),
}
