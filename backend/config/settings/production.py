"""Production settings. `manage.py check --deploy` must be clean against this."""

from .base import *  # noqa: F403
from .base import env, env_bool, env_list

DEBUG = False

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production")

if env("DJANGO_SECRET_KEY") in {"", "insecure-dev-key-override-in-production"}:
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# --- Transport security -----------------------------------------------------

# TLS is terminated upstream; the proxy must set X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

X_FRAME_OPTIONS = "DENY"

# --- Database ---------------------------------------------------------------

# PgBouncer in transaction mode is assumed, which is exactly why the audit
# actor is set with SET LOCAL inside the request transaction rather than once
# per connection. Server-side cursors do not survive transaction pooling.
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True  # noqa: F405
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache_table",
    }
}
