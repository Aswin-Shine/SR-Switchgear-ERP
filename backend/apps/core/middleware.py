"""Request-scoped plumbing.

Both middlewares are thin. The logic they lean on lives in ``apps.core.db`` and
``apps.core.exceptions``, which land in Phase 1 precisely so the test suite can
use them without a request.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.core.db import ACTOR_SETTING
from apps.core.exceptions import DomainError

logger = logging.getLogger(__name__)


class AuditActorMiddleware:
    """Tell ``core.record_audit()`` who is making this request.

    ``ATOMIC_REQUESTS = True`` means Django has already opened a transaction by
    the time this runs, so ``SET LOCAL`` binds to the request's transaction and
    is discarded at commit. That is what makes PgBouncer transaction pooling
    safe: the next borrower of the connection cannot inherit this actor.

    This does not call ``audit_actor()`` — that helper opens its own
    transaction, and nesting one here would create a savepoint for nothing.
    Both write the same GUC.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        user_id = getattr(user, "pk", None) if (user and user.is_authenticated) else None

        if user_id is not None:
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL {ACTOR_SETTING} = %s", [str(user_id)])

        return self.get_response(request)


class DomainErrorMiddleware:
    """Map the domain exception hierarchy to HTTP status codes, in one place.

    PermissionDenied -> 403, RuleViolation -> 422, StaleTransition -> 409,
    NotFound -> 404, ConfigurationError -> 500.

    Only ``/api/`` paths get a JSON body; everything else is re-raised so the
    admin and the server-rendered pages keep Django's own error handling.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception):
        if not isinstance(exception, DomainError):
            return None
        if not request.path.startswith("/api/"):
            return None

        if exception.status_code >= 500:
            logger.error("Configuration error on %s: %s", request.path, exception.message)

        payload = {
            "error": {
                "code": exception.code,
                "message": exception.message,
            }
        }
        if exception.context:
            payload["error"]["context"] = exception.context
        return JsonResponse(payload, status=exception.status_code)
