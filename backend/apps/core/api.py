"""Shared helpers for the hand-written JSON API.

D1 chose a React SPA served by plain Django views rather than DRF. That is a
smaller dependency surface, but it means there is no serializer layer and no
generated schema — so the shape of every response is decided here and in the
view functions, and pinned by contract tests rather than by a framework.

Three consequences worth being deliberate about:

* every endpoint declares its allowed methods, because Django will happily
  route a POST to a function that only meant to answer GET;
* pagination has one shape, defined once;
* errors come out of ``DomainErrorMiddleware``, so a view raises
  ``RuleViolation`` and never builds a 422 by hand.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Iterable
from typing import Any

from django.core.paginator import EmptyPage, Paginator
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse

from apps.core.exceptions import RuleViolation

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def json_body(request: HttpRequest) -> dict[str, Any]:
    """Parse a JSON request body into a dict.

    A malformed body is a client error, not a 500, so it becomes
    ``RuleViolation`` and the middleware renders it as 422.
    """
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuleViolation(f"Request body is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuleViolation("Request body must be a JSON object.")
    return payload


def require(payload: dict[str, Any], *keys: str) -> tuple:
    """Pull required keys out of a payload, or explain precisely what is missing."""
    missing = [key for key in keys if payload.get(key) in (None, "")]
    if missing:
        raise RuleViolation(
            f"Missing required field(s): {', '.join(missing)}.", missing=missing
        )
    return tuple(payload[key] for key in keys)


def paginate(
    queryset: QuerySet | list,
    request: HttpRequest,
    serialize: Callable[[Any], dict],
) -> dict[str, Any]:
    """One pagination shape for the whole API.

    ``page`` is 1-based. An out-of-range page returns an empty ``items`` list
    rather than a 404: a client polling page 3 while rows are deleted beneath
    it should see "nothing here", not an error.
    """
    try:
        page_number = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        raise RuleViolation("page must be an integer.") from None
    try:
        page_size = int(request.GET.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        raise RuleViolation("page_size must be an integer.") from None

    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    page_number = max(1, page_number)

    paginator = Paginator(queryset, page_size)
    try:
        page = paginator.page(page_number)
        items = [serialize(obj) for obj in page.object_list]
    except EmptyPage:
        items = []

    return {
        "items": items,
        "page": page_number,
        "page_size": page_size,
        "total": paginator.count,
        "pages": paginator.num_pages,
    }


def api(methods: Iterable[str], *, login_required: bool = True):
    """Declare an endpoint: its methods, and whether it needs a session.

    Returns 405 with an ``Allow`` header for the wrong method and 401 for an
    anonymous caller. 401 rather than a redirect to the login page, because the
    caller is an XHR and a 302 to HTML would be unreadable to it.
    """
    allowed = {m.upper() for m in methods}
    if "GET" in allowed:
        allowed.add("HEAD")

    def decorator(view: Callable[..., JsonResponse]):
        @functools.wraps(view)
        def wrapper(request: HttpRequest, *args, **kwargs):
            if request.method not in allowed:
                response = JsonResponse(
                    {
                        "error": {
                            "code": "method_not_allowed",
                            "message": f"{request.method} is not allowed here.",
                        }
                    },
                    status=405,
                )
                response["Allow"] = ", ".join(sorted(allowed))
                return response

            if login_required and not request.user.is_authenticated:
                return JsonResponse(
                    {
                        "error": {
                            "code": "authentication_required",
                            "message": "Sign in to continue.",
                        }
                    },
                    status=401,
                )

            return view(request, *args, **kwargs)

        return wrapper

    return decorator


#: Alias matching the name BACKEND_PLAN.md phase 2.5 uses.
require_session = functools.partial(api, login_required=True)


def ok(payload: dict[str, Any], status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status)


def created(payload: dict[str, Any]) -> JsonResponse:
    return JsonResponse(payload, status=201)


def no_content() -> JsonResponse:
    return JsonResponse({}, status=204)


def iso(value) -> str | None:
    """Timestamps and dates cross the wire as ISO 8601 strings, or null."""
    return value.isoformat() if value is not None else None


def decimal_str(value) -> str | None:
    """Money crosses the wire as a string.

    A NUMERIC(14,2) does not survive a round trip through JavaScript's float,
    and a quotation total that reads 1234567.89 in the database and
    1234567.8899999999 in the browser is the kind of defect nobody finds until
    a client disputes an invoice.
    """
    return None if value is None else str(value)
