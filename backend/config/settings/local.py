"""Development settings."""

from pathlib import Path

from .base import *  # noqa: F403
from .base import STATIC_ROOT, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = ["*"]

# WhiteNoise warns on every request if STATIC_ROOT does not exist, and in
# development nobody has run collectstatic yet.
Path(STATIC_ROOT).mkdir(parents=True, exist_ok=True)

# Fast hashing keeps the fixture chain (department -> employee -> user account
# -> client -> job card -> job line) from dominating test runtime.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# The manifest storage demands a collectstatic run; not wanted in development.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
