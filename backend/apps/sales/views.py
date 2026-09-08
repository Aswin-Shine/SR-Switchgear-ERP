"""Server-rendered, non-JSON views for the sales domain.

Print stays server-rendered rather than a client-side render-to-PDF: fidelity
is better, and anyone who can see the job card detail page already holds
job_card:view, which is all print needs too — there is no separate "print"
permission in the real grant model (frontend/src/features/job-cards/
JobCardDetailPage.tsx explains this at the link itself).
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.identity import constants
from apps.identity.services import has_permission
from apps.sales import selectors, services
from apps.sales.models import JobCard, JobLifecycleStatus

#: Matches frontend/src/lib/format.ts's EMPTY_MARK exactly — the same glyph
#: for "nothing to show" everywhere in the app, print included.
EMPTY_MARK = "—"


def _format_inr(amount: Decimal | None) -> str:
    """``Decimal("1234567.5")`` -> ``"₹12,34,567.50"``.

    Mirrors the frontend's ``formatMoney()`` (Intl.NumberFormat("en-IN")):
    the last 3 digits of the integer part stand alone, everything before
    that groups in pairs. Python's Decimal is already exact, so — unlike
    the JS client — there's no float-precision reason to avoid arithmetic
    here; this is pure string formatting.
    """
    if amount is None:
        return EMPTY_MARK

    sign = "-" if amount < 0 else ""
    quantized = abs(amount).quantize(Decimal("0.01"))
    int_part, _, frac_part = str(quantized).partition(".")

    if len(int_part) <= 3:
        grouped = int_part
    else:
        last_three = int_part[-3:]
        rest = int_part[:-3]
        pairs: list[str] = []
        while len(rest) > 2:
            pairs.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            pairs.insert(0, rest)
        grouped = ",".join([*pairs, last_three])

    return f"{sign}₹{grouped}.{frac_part}"


def print_job_card(request: HttpRequest, job_no: str) -> HttpResponse:
    """A printable job card: production details plus the current quotation.

    Looked up by ``job_no`` (e.g. ``JOB-2026-00028``), not the card's UUID —
    unconditionally unique (``uk_job_cards_job_no``, no soft-delete
    exception), so this is exactly as collision-safe as a ``pk`` lookup, and
    gives the printed page's own URL a readable identifier instead of one.

    Not wrapped by ``apps.core.api.api`` (JSON-only, D1) — this is a plain
    HTML page, so permission is checked as a boolean
    (``has_permission``) rather than raised (``require_permission``):
    ``apps.core.exceptions.PermissionDenied`` is only mapped to a response
    by ``DomainErrorMiddleware`` for ``/api/`` paths, and this lives at
    ``/print/...``.
    """
    card = get_object_or_404(
        JobCard.objects.select_related("client", "owner_user", "client_contact"),
        job_no=job_no,
        deleted_at__isnull=True,
    )

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not has_permission(request.user, constants.RES_JOB_CARD, "view", obj=card):
        return HttpResponseForbidden("You do not have permission to view this job card.")

    quotation = services.current_quotation(card)

    return render(
        request,
        "sales/print_job_card.html",
        {
            "card": card,
            # lifecycle_status is CHECK-pinned (ck_job_cards_lifecycle) — the one
            # sanctioned exception to never comparing a status against a literal.
            "is_dead": card.lifecycle_status
            in {JobLifecycleStatus.CANCELLED, JobLifecycleStatus.LOST},
            "lines": selectors.lines_for(card),
            "quotation": quotation,
            "quotation_amount": _format_inr(quotation.quoted_amount) if quotation else None,
            "requirements": (card.requirements or {}).items(),
            "printed_at": timezone.now(),
        },
    )
