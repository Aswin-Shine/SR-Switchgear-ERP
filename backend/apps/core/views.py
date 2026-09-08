"""Operational endpoints."""

from __future__ import annotations

from django.core.files.storage import default_storage
from django.db import connection
from django.http import FileResponse, HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache

from apps.core.models import Document


@never_cache
def document_download(request: HttpRequest, document_id, filename: str) -> FileResponse:
    """Filesystem-storage fallback so a download shows a real filename
    instead of the opaque storage-key UUID.

    Same trust model as ``django.views.static.serve`` at ``/media/<path>``
    (see ``config/urls.py`` — this route only exists when
    ``STORAGE_BACKEND=filesystem``): the URL itself is the delivery
    mechanism, not a new authorisation boundary — permission was already
    checked by whichever API view called ``apps.core.services.document_url``
    to produce it. ``filename`` is purely a display hint for
    Content-Disposition; ``FileResponse`` encodes it safely regardless of
    its contents, so there's nothing to sanitise further here.
    """
    document = get_object_or_404(Document, pk=document_id)
    file = default_storage.open(document.storage_key, "rb")
    return FileResponse(file, filename=filename, content_type=document.mime_type)


@never_cache
def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness plus database reachability. The container HEALTHCHECK hits this.

    A process that is up but cannot reach PostgreSQL is not healthy — every
    request it serves will fail — so this deliberately touches the database
    rather than returning a static 200.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return JsonResponse(
            {"status": "unhealthy", "database": str(exc)[:200]}, status=503
        )

    return JsonResponse({"status": "ok", "database": "ok"})
