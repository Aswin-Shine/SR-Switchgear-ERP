"""Settings shared by every environment.

Two settings here are load-bearing and must not be moved to a later phase:

* ``AUTH_USER_MODEL`` is set before any migration exists. Django bakes the user
  model into migration state; changing it after the first ``migrate`` is a
  rebuild, not an edit.
* ``ATOMIC_REQUESTS`` is on because the audit actor is set with ``SET LOCAL``,
  which only survives inside a transaction. Without a request-scoped
  transaction every audit row would be attributed to nobody.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def env_list(key: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


# --- Core -------------------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-override-in-production")
DEBUG = False
ALLOWED_HOSTS: list[str] = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Deviation 3.11: our RBAC lives in auth_roles / auth_permissions, not Django's.
# django.contrib.auth is still installed — we use its password hashers,
# validators and the admin's session plumbing — but every one of our models
# declares default_permissions = (), so auth_permission stays empty of our
# models and Group is unregistered from the admin.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.identity",
    "apps.hr",
    "apps.pipeline",
    "apps.sales",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Phase 6. Sets app.current_user_id for the request's transaction, and maps
    # apps.core.exceptions.DomainError to HTTP status codes.
    "apps.core.middleware.AuditActorMiddleware",
    "apps.core.middleware.DomainErrorMiddleware",
]

_FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ([_FRONTEND_DIST] if _FRONTEND_DIST.exists() else []) + [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "srerp"),
        "USER": env("POSTGRES_USER", "srerp"),
        "PASSWORD": env("POSTGRES_PASSWORD", "srerp"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        # Every request runs in a transaction. See the module docstring.
        "ATOMIC_REQUESTS": True,
        # sales_job_cards.enquiry_date defaults to CURRENT_DATE, which is the
        # database session's date. Pinning the connection to Asia/Kolkata stops
        # an enquiry logged at 00:30 IST from being dated the previous day.
        "TIME_ZONE": "Asia/Kolkata",
    }
}

# --- Identity ---------------------------------------------------------------

AUTH_USER_MODEL = "identity.UserAccount"
AUTHENTICATION_BACKENDS = ["apps.identity.backends.LockoutModelBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/app/"
LOGOUT_REDIRECT_URL = "/login/"

# Drives auth_user_accounts.failed_login_count / locked_until. No rate-limiting
# dependency: the columns already exist (BACKEND_PLAN.md section 7).
LOGIN_MAX_FAILURES = env_int("LOGIN_MAX_FAILURES", 5)
LOGIN_LOCKOUT_MINUTES = env_int("LOGIN_LOCKOUT_MINUTES", 15)

# --- Internationalisation ---------------------------------------------------

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --- Static and media -------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = env("DJANGO_STATIC_ROOT", "/tmp/static")  # noqa: S108 — read-only rootfs
# Vite builds with base: "/static/spa/" (see frontend/vite.config.ts), so the
# built assets must be namespaced under a "spa" prefix here too — plain
# `[_FRONTEND_DIST]` would publish them at /static/<file> instead of
# /static/spa/<file> and every asset URL the built index.html references
# would 404.
STATICFILES_DIRS = [("spa", _FRONTEND_DIST)] if _FRONTEND_DIST.exists() else []

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

# --- Sessions ---------------------------------------------------------------

# D11: auth_sessions is created but never written to. Browser sessions live in
# django_session, per the prompt's ban on JWT.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True  # The SPA reads the token from a meta tag.
CSRF_COOKIE_SAMESITE = "Lax"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "srerp",
    }
}

# --- Audit ------------------------------------------------------------------

# D10: how many quarters of core_audit_logs partitions to keep open ahead of
# now. The entrypoint runs `manage.py ensure_audit_partitions` after `migrate`.
AUDIT_PARTITION_QUARTERS_AHEAD = env_int("AUDIT_PARTITION_QUARTERS_AHEAD", 8)

# --- Object storage (Phase 3, D9) -------------------------------------------

STORAGE_BACKEND = env("STORAGE_BACKEND", "filesystem")

if STORAGE_BACKEND == "s3":
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "endpoint_url": env("AWS_S3_ENDPOINT_URL") or None,
            "access_key": env("AWS_ACCESS_KEY_ID"),
            "secret_key": env("AWS_SECRET_ACCESS_KEY"),
            "bucket_name": env("AWS_STORAGE_BUCKET_NAME", "srerp-documents"),
            "region_name": env("AWS_S3_REGION_NAME", "us-east-1"),
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": 900,
        },
    }

# Largest accepted upload, in bytes.
MAX_UPLOAD_BYTES = env_int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024)

# Quotation PDFs specifically are capped tighter than the general upload limit.
QUOTATION_PDF_MAX_BYTES = env_int("QUOTATION_PDF_MAX_BYTES", 5 * 1024 * 1024)

# --- Logging ----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"],
                               "propagate": False},
    },
}
