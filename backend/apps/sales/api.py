"""Sales endpoints — roughly two dozen thin wrappers over ``sales.services``.

Every one of these is orchestration: parse, look up, call a service, serialise.
No business rule lives in this module. Errors are raised by the services and
mapped to status codes by ``DomainErrorMiddleware``, so no view builds a 403 or
a 422 by hand.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.core.api import (
    api,
    created,
    decimal_str,
    iso,
    json_body,
    no_content,
    ok,
    paginate,
    require,
)
from apps.core.exceptions import NotFound, RuleViolation
from apps.core.services import document_url
from apps.identity import constants
from apps.identity.services import owner_scope_for, require_permission
from apps.pipeline.api import serialize_board_line, serialize_stage
from apps.pipeline.models import JobLineTransition
from apps.pipeline.selectors import available_actions_bulk
from apps.sales import selectors, services
from apps.sales.models import (
    Client,
    JobAttachment,
    JobCard,
    JobLine,
    JobLineStatus,
    ProductCategory,
    Quotation,
)

# --- serialisers ---------------------------------------------------------------


def serialize_product_category(category: ProductCategory) -> dict:
    return {
        "id": str(category.id),
        "code": str(category.code),
        "name": category.name,
        "is_manufactured": category.is_manufactured,
    }


def serialize_client(client: Client) -> dict:
    return {
        "id": str(client.id),
        "client_code": str(client.client_code),
        "legal_name": client.legal_name,
        "gstin": client.gstin,
        "billing_city": client.billing_city,
        "billing_state": client.billing_state,
        "default_dispatch_policy": client.default_dispatch_policy,
        "is_active": client.is_active,
    }


def serialize_contact(contact) -> dict:
    return {
        "id": str(contact.id),
        "contact_name": contact.contact_name,
        "phone": contact.phone,
        "email": str(contact.email) if contact.email else None,
        "is_primary": contact.is_primary,
    }


def serialize_job_card(card: JobCard) -> dict:
    return {
        "id": str(card.id),
        "job_no": card.job_no,
        "client": {
            "id": str(card.client_id),
            "client_code": str(card.client.client_code),
            "legal_name": card.client.legal_name,
        },
        "client_contact": (
            serialize_contact(card.client_contact) if card.client_contact_id else None
        ),
        "owner_user": {
            "id": str(card.owner_user_id),
            "username": card.owner_user.username,
        },
        "lifecycle_status": card.lifecycle_status,
        "enquiry_source": card.enquiry_source,
        "dispatch_policy": card.dispatch_policy,
        "enquiry_date": iso(card.enquiry_date),
        "required_by": iso(card.required_by),
        "requirements": card.requirements,
    }


def serialize_job_line(line: JobLine) -> dict:
    return {
        "id": str(line.id),
        "line_no": line.line_no,
        "product_category": serialize_product_category(line.product_category),
        "description": line.description,
        "quantity": line.quantity,
        "line_status": line.line_status,
        "required_by": iso(line.required_by),
        "specs": line.specs,
        "current_stage": {
            "id": str(line.current_stage_id),
            "code": str(line.current_stage.code),
            "name": line.current_stage.name,
        },
    }


def serialize_quotation(quotation: Quotation) -> dict:
    return {
        "id": str(quotation.id),
        "quotation_no": quotation.quotation_no,
        "revision_no": quotation.revision_no,
        "status": quotation.status,
        "supersedes_id": str(quotation.supersedes_id) if quotation.supersedes_id else None,
        # A string, not a float: NUMERIC(14,2) does not survive a round trip
        # through JavaScript's number type.
        "quoted_amount": decimal_str(quotation.quoted_amount),
        "currency": quotation.currency,
        "valid_till": iso(quotation.valid_till),
        "has_pdf": quotation.pdf_document_id is not None,
        "prepared_by": quotation.prepared_by.username,
    }


def serialize_note(note) -> dict:
    return {
        "id": str(note.id),
        "body": note.body,
        "author": note.author_user.username,
        "job_line_id": str(note.job_line_id) if note.job_line_id else None,
        "created_at": iso(note.created_at),
    }


def serialize_attachment(attachment) -> dict:
    return {
        "id": str(attachment.id),
        "label": attachment.label,
        "filename": attachment.document.original_filename,
        "mime_type": attachment.document.mime_type,
        "byte_size": attachment.document.byte_size,
        "job_line_id": str(attachment.job_line_id) if attachment.job_line_id else None,
        "attached_by": attachment.attached_by.username,
        "attached_at": iso(attachment.attached_at),
    }


# --- reference -------------------------------------------------------------------


@api(["GET"])
def product_categories(request: HttpRequest) -> JsonResponse:
    categories = ProductCategory.objects.filter(is_active=True).order_by("code")
    return ok({"items": [serialize_product_category(c) for c in categories]})


# --- clients ----------------------------------------------------------------------


@api(["GET", "POST"])
def clients(request: HttpRequest) -> JsonResponse:
    if request.method == "POST":
        payload = json_body(request)
        require(payload, "legal_name")
        client = services.create_client(request.user, **payload)
        return created(serialize_client(client))

    require_permission(request.user, constants.RES_CLIENT, "view")
    queryset = selectors.search_clients(
        request.GET.get("q", ""), active_only=request.GET.get("active") == "1"
    )
    return ok(paginate(queryset, request, serialize_client))


@api(["GET", "PATCH"])
def client_detail(request: HttpRequest, client_id) -> JsonResponse:
    client = get_object_or_404(Client, pk=client_id, deleted_at__isnull=True)

    if request.method == "PATCH":
        services.update_client(request.user, client, **json_body(request))
        return ok(serialize_client(client))

    require_permission(request.user, constants.RES_CLIENT, "view", obj=client)
    payload = serialize_client(client)
    payload["contacts"] = [serialize_contact(c) for c in selectors.contacts_for(client)]
    return ok(payload)


@api(["POST"])
def client_contacts(request: HttpRequest, client_id) -> JsonResponse:
    client = get_object_or_404(Client, pk=client_id, deleted_at__isnull=True)
    payload = json_body(request)
    require(payload, "contact_name")
    contact = services.add_client_contact(request.user, client, **payload)
    return created(serialize_contact(contact))


# --- job cards ----------------------------------------------------------------------


@api(["GET", "POST"])
def job_cards(request: HttpRequest) -> JsonResponse:
    if request.method == "POST":
        payload = json_body(request)
        (client_id,) = require(payload, "client_id")
        client = get_object_or_404(Client, pk=client_id, deleted_at__isnull=True)
        card = services.create_job_card(
            request.user,
            client,
            dispatch_policy=payload.pop("dispatch_policy", None),
            **{k: v for k, v in payload.items() if k != "client_id"},
        )
        card.refresh_from_db()
        return created(serialize_job_card(card))

    scope = owner_scope_for(request.user, constants.RES_JOB_CARD, "view")
    queryset = selectors.search_job_cards(
        request.GET.get("q", ""),
        status=request.GET.get("status", ""),
        owner_user=scope or (request.user if request.GET.get("mine") == "1" else None),
        client_id=request.GET.get("client_id") or None,
    )
    return ok(paginate(queryset, request, serialize_job_card))


@api(["GET", "PATCH"])
def job_card_detail(request: HttpRequest, card_id) -> JsonResponse:
    card = get_object_or_404(
        JobCard.objects.select_related("client", "owner_user", "client_contact"),
        pk=card_id,
        deleted_at__isnull=True,
    )

    if request.method == "PATCH":
        services.update_job_card(request.user, card, **json_body(request))
        return ok(serialize_job_card(card))

    require_permission(request.user, constants.RES_JOB_CARD, "view", obj=card)
    payload = serialize_job_card(card)
    payload["lines"] = [serialize_job_line(line) for line in selectors.lines_for(card)]
    payload["quotations"] = [
        serialize_quotation(q) for q in selectors.quotations_for(card)
    ]
    current = services.current_quotation(card)
    payload["current_quotation_id"] = str(current.id) if current else None
    return ok(payload)


@api(["POST"])
def cancel_job_card(request: HttpRequest, card_id) -> JsonResponse:
    card = get_object_or_404(JobCard, pk=card_id, deleted_at__isnull=True)
    payload = json_body(request)
    (reason,) = require(payload, "reason")
    services.cancel_job_card(request.user, card, reason)
    card.refresh_from_db()
    return ok(serialize_job_card(card))


# --- job lines -----------------------------------------------------------------------


@api(["GET", "POST"])
def job_card_lines(request: HttpRequest, card_id) -> JsonResponse:
    card = get_object_or_404(JobCard, pk=card_id, deleted_at__isnull=True)

    if request.method == "POST":
        payload = json_body(request)
        (category_id, description) = require(payload, "product_category_id", "description")
        category = get_object_or_404(ProductCategory, pk=category_id)
        line = services.add_job_line(
            request.user,
            card,
            product_category=category,
            description=description,
            **{
                k: v
                for k, v in payload.items()
                if k in {"quantity", "line_no", "required_by", "specs", "line_status"}
            },
        )
        line.refresh_from_db()
        return created(serialize_job_line(line))

    require_permission(request.user, constants.RES_JOB_LINE, "view", obj=card)
    return ok({"items": [serialize_job_line(line) for line in selectors.lines_for(card)]})


@api(["PATCH"])
def job_line_update(request: HttpRequest, line_id) -> JsonResponse:
    line = get_object_or_404(
        JobLine.objects.select_related("product_category", "current_stage", "job_card"),
        pk=line_id,
        deleted_at__isnull=True,
    )
    services.update_job_line(request.user, line, **json_body(request))
    return ok(serialize_job_line(line))


# --- notes and attachments ----------------------------------------------------------------


@api(["GET", "POST"])
def job_card_notes(request: HttpRequest, card_id) -> JsonResponse:
    card = get_object_or_404(JobCard, pk=card_id, deleted_at__isnull=True)

    if request.method == "POST":
        payload = json_body(request)
        (body,) = require(payload, "body")
        line = _optional_line(card, payload.get("job_line_id"))
        note = services.add_note(request.user, card, body, job_line=line)
        return created(serialize_note(note))

    require_permission(request.user, constants.RES_JOB_CARD, "view", obj=card)
    return ok({"items": [serialize_note(n) for n in selectors.notes_for(card)]})


@api(["GET", "POST"])
def job_card_attachments(request: HttpRequest, card_id) -> JsonResponse:
    card = get_object_or_404(JobCard, pk=card_id, deleted_at__isnull=True)

    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            raise RuleViolation("Attach a file under the field name 'file'.")
        line = _optional_line(card, request.POST.get("job_line_id"))
        attachment = services.attach_file(
            request.user, card, upload, label=request.POST.get("label") or None, job_line=line
        )
        return created(serialize_attachment(attachment))

    require_permission(request.user, constants.RES_JOB_CARD, "view", obj=card)
    return ok({"items": [serialize_attachment(a) for a in selectors.attachments_for(card)]})


@api(["DELETE"])
def job_card_attachment_detail(request: HttpRequest, card_id, attachment_id) -> JsonResponse:
    card = get_object_or_404(JobCard, pk=card_id, deleted_at__isnull=True)
    attachment = get_object_or_404(JobAttachment, pk=attachment_id, job_card=card)
    services.remove_attachment(request.user, card, attachment)
    return no_content()


@api(["GET"])
def attachment_download(request: HttpRequest, attachment_id) -> HttpResponseRedirect:
    """Redirect to a time-limited storage URL rather than proxying the bytes.

    Same reasoning as ``quotation_pdf``: the permission check happens here,
    on every request, before handing out the signed URL — the URL is the
    delivery mechanism, not the authorisation.
    """
    attachment = get_object_or_404(JobAttachment, pk=attachment_id)
    require_permission(request.user, constants.RES_JOB_CARD, "view", obj=attachment.job_card)
    return HttpResponseRedirect(document_url(attachment.document))


def _optional_line(card: JobCard, line_id) -> JobLine | None:
    if not line_id:
        return None
    line = JobLine.objects.filter(pk=line_id, deleted_at__isnull=True).first()
    if line is None:
        raise NotFound("That job line does not exist.")
    return line


# --- quotations --------------------------------------------------------------------------------


@api(["GET", "POST"])
def job_card_quotations(request: HttpRequest, card_id) -> JsonResponse:
    card = get_object_or_404(JobCard, pk=card_id, deleted_at__isnull=True)

    if request.method == "POST":
        # Multipart: the PDF arrives with the revision — create_quotation_revision
        # raises if it's missing, since a revision without one doesn't fit
        # this system's actual process.
        quoted_amount = _optional_decimal(request.POST.get("quoted_amount"))
        quotation = services.create_quotation_revision(
            request.user,
            card,
            quoted_amount=quoted_amount,
            pdf=request.FILES.get("pdf"),
            valid_till=request.POST.get("valid_till") or None,
        )
        quotation.refresh_from_db()
        return created(serialize_quotation(quotation))

    require_permission(request.user, constants.RES_QUOTATION, "view", obj=card)
    return ok({"items": [serialize_quotation(q) for q in selectors.quotations_for(card)]})


def _optional_decimal(raw: str | None) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError) as exc:
        raise RuleViolation(f"{raw!r} is not a valid amount.") from exc


@api(["GET"])
def quotation_detail(request: HttpRequest, quotation_id) -> JsonResponse:
    quotation = _get_quotation(quotation_id)
    require_permission(request.user, constants.RES_QUOTATION, "view", obj=quotation)

    payload = serialize_quotation(quotation)
    payload["lines"] = [
        {
            "job_line_id": str(line.job_line_id),
            "line_no": line.job_line.line_no,
            "description": line.job_line.description,
            "line_amount": decimal_str(line.line_amount),
        }
        for line in selectors.quotation_lines_for(quotation)
    ]
    return ok(payload)


@api(["GET"])
def quotation_pdf(request: HttpRequest, quotation_id):
    """Redirect to a time-limited storage URL rather than proxying the bytes.

    A gunicorn worker streaming a 4MB PDF is a worker not serving requests, and
    object storage can sign a short-lived URL far more cheaply than we can
    relay one. The permission check still happens here, on every request — the
    signed URL is the delivery mechanism, not the authorisation.
    """
    quotation = _get_quotation(quotation_id)
    require_permission(request.user, constants.RES_QUOTATION, "view", obj=quotation)

    if quotation.pdf_document_id is None:
        raise NotFound("That quotation has no PDF attached.")

    return HttpResponseRedirect(document_url(quotation.pdf_document))


def _get_quotation(quotation_id) -> Quotation:
    return get_object_or_404(
        Quotation.objects.select_related("job_card", "pdf_document", "prepared_by"),
        pk=quotation_id,
    )


# --- dashboard -----------------------------------------------------------------------

# How far back "Recent activity" looks — old transitions age out of the panel
# on their own instead of only being pushed out by the next 20 newer ones.
RECENT_ACTIVITY_WINDOW = timedelta(days=7)


@api(["GET"])
def dashboard(request: HttpRequest) -> JsonResponse:
    """Everything the landing screen needs, in three bounded queries plus the
    board's own bulk-actions cost: the user's open job cards (with line
    counts — see the module docstring on why those are computed only here,
    not on the general job-cards list), lines they have a real move on right
    now, and recent activity on cards they own.
    """
    user = request.user
    # The dashboard is always "my own stuff" regardless of scope class — this
    # call exists to raise when the actor holds no job_card:view grant at
    # all, not to decide what "my own" means; `cards` below is already
    # filtered to `user` either way.
    scope = owner_scope_for(user, constants.RES_JOB_CARD, "view")

    cards = selectors.open_job_cards_for(user).annotate(
        line_count=Count("lines", distinct=True),
        open_line_count=Count(
            "lines", filter=Q(lines__line_status=JobLineStatus.ACTIVE), distinct=True
        ),
    )
    my_open_job_cards = []
    for card in cards:
        payload = serialize_job_card(card)
        payload["line_count"] = card.line_count
        payload["open_line_count"] = card.open_line_count
        my_open_job_cards.append(payload)

    lines_qs = JobLine.objects.filter(
        deleted_at__isnull=True, job_card__deleted_at__isnull=True
    ).select_related("job_card", "job_card__client", "product_category", "current_stage")
    if scope is not None:
        # An owner-scoped viewer's "lines awaiting me" must stay inside their
        # own cards too — otherwise this panel would leak every other Sales
        # rep's actionable line even though the board and job-card list don't.
        lines_qs = lines_qs.filter(job_card__owner_user=scope)
    lines = list(lines_qs)
    actions_by_line = available_actions_bulk(user, lines)
    lines_awaiting_me = []
    for line in lines:
        line_actions = actions_by_line.get(line.pk, [])
        if not any(action["available"] for action in line_actions):
            continue
        payload = serialize_board_line(line, line_actions)
        payload["current_stage"] = serialize_stage(line.current_stage)
        lines_awaiting_me.append(payload)

    transitions = (
        JobLineTransition.objects.filter(
            job_line__job_card__owner_user=user,
            performed_at__gte=timezone.now() - RECENT_ACTIVITY_WINDOW,
        )
        .select_related("from_stage", "to_stage", "performed_by")
        .order_by("-performed_at", "-id")[:20]
    )
    recent_activity = [
        {
            "id": transition.id,
            "from_stage": (
                str(transition.from_stage.code) if transition.from_stage_id else None
            ),
            "to_stage": str(transition.to_stage.code),
            "action_code": transition.action_code,
            "performed_by": transition.performed_by.username,
            "performed_at": iso(transition.performed_at),
            "note": transition.note,
        }
        for transition in transitions
    ]

    return ok(
        {
            "my_open_job_cards": my_open_job_cards,
            "lines_awaiting_me": lines_awaiting_me,
            "recent_activity": recent_activity,
        }
    )
