"""Root URL configuration.

Three delivery surfaces, per D1 / FRONTEND_PLAN.md:

* ``/admin/``  — Django admin for HR, roles, permissions, masters, audit log.
* ``/api/v1/`` — hand-written JSON views for the React SPA. No DRF.
* ``/login/``  — server-rendered login and password change.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve as serve_media

from apps.core import views as core_views

urlpatterns = [
    path("healthz/", core_views.healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("api/v1/", include(("config.api_urls", "api"), namespace="api")),
    path("", include("apps.identity.urls")),
]

# apps.core.services.document_url() redirects here for the filesystem
# storage backend (S3 redirects straight to a signed bucket URL instead —
# this route is never hit in that mode). Without it, MEDIA_ROOT has nothing
# serving MEDIA_URL and every "Open PDF"/attachment link 404s even though
# the file is sitting right there on disk. django.views.static.serve isn't
# meant for real production traffic (no signed expiry, ties up a worker
# streaming the file) — it's here only because STORAGE_BACKEND=filesystem
# is itself a local/self-hosted fallback; a real deployment sets
# STORAGE_BACKEND=s3 (real S3 or the bundled `minio` profile) instead.
if settings.STORAGE_BACKEND == "filesystem":
    urlpatterns += [
        path("media/<path:path>", serve_media, {"document_root": str(settings.MEDIA_ROOT)}),
    ]
