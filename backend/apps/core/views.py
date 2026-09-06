"""Operational endpoints."""

from __future__ import annotations

from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache


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
