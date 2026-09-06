"""Sales: clients, job cards, job lines, quotations, notes and attachments.

Two rules in this module carry more weight than the rest.

**Dispatch policy is copied, not referenced.** ``job_cards.dispatch_policy`` is
seeded from ``clients.default_dispatch_policy`` at creation and is thereafter
independent. Changing a client's default must never retroactively alter orders
already placed — the whole reason the column is audited is so a dispute over
whether partial shipment was authorised can be settled from the record.

**The quotation status machine is enforced here (D7).** The CHECK constraint
pins the domain but says nothing about the order, and the partial unique index
covers only ``active`` — not ``sent``. So "the current quotation" cannot be
read off the index alone; it is defined below.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.core.db import audit_actor
from apps.core.exceptions import DomainError, NotFound, PermissionDenied, RuleViolation
from apps.core.numbering import next_client_code, next_job_no, next_quotation_no
from apps.core.services import upload_document
from apps.identity import constants
from apps.identity.services import require_permission
from apps.pipeline.selectors import initial_stage
from apps.pipeline.services import perform_transition
from apps.sales import selectors as sales_selectors
from apps.sales.models import (
    Client,
    ClientContact,
    DispatchPolicy,
    JobAttachment,
    JobCard,
    JobLifecycleStatus,
    JobLine,
    JobNote,
    Quotation,
    QuotationLine,
    QuotationStatus,
)

logger = logging.getLogger(__name__)


# --- clients ------------------------------------------------------------------


def create_client(actor, **fields: Any) -> Client:
    require_permission(actor, constants.RES_CLIENT, "create")
    _reject_unknown(fields, _CLIENT_FIELDS, "client")

    with audit_actor(actor):
        try:
            return Client.objects.create(
                created_by=actor, client_code=next_client_code(), **fields
            )
        except IntegrityError as exc:
            raise RuleViolation(_explain_client(exc)) from exc


def update_client(actor, client: Client, **fields: Any) -> Client:
    require_permission(actor, constants.RES_CLIENT, "edit", obj=client)
    _reject_unknown(fields, _CLIENT_FIELDS, "client")
    if not fields:
        return client

    for name, value in fields.items():
        setattr(client, name, value)

    with audit_actor(actor):
        try:
            client.save(update_fields=sorted(fields))
        except IntegrityError as exc:
            raise RuleViolation(_explain_client(exc)) from exc
    return client


#: client_code is deliberately absent — issued only by next_client_code(),
#: never caller-supplied. See create_client and ClientAdmin.save_model.
_CLIENT_FIELDS = frozenset(
    {
        "legal_name",
        "gstin",
        "billing_city",
        "billing_state",
        "default_dispatch_policy",
        "is_active",
    }
)


def _explain_client(exc: IntegrityError) -> str:
    text = str(exc)
    if "uk_clients_code" in text:
        return "That client code is already in use."
    if "uk_clients_gstin" in text:
        return "That GSTIN is already registered to another client."
    if "ck_clients_gstin" in text:
        return "That GSTIN is not a valid 15-character GSTIN."
    if "ck_clients_dispatch" in text:
        return "That dispatch policy is not one of the permitted values."
    return "That change conflicts with an existing client record."


def add_client_contact(actor, client: Client, **fields: Any) -> ClientContact:
    require_permission(actor, constants.RES_CLIENT, "edit", obj=client)
    _reject_unknown(
        fields, {"contact_name", "phone", "email", "is_primary"}, "client contact"
    )

    with audit_actor(actor):
        if fields.get("is_primary"):
            # One primary per client (uk_client_contacts_primary). Demote the
            # incumbent rather than making the caller do it in two steps and
            # discover the constraint the hard way.
            ClientContact.objects.filter(
                client=client, is_primary=True, deleted_at__isnull=True
            ).update(is_primary=False)
        try:
            return ClientContact.objects.create(client=client, **fields)
        except IntegrityError as exc:
            if "ck_client_contacts_reach" in str(exc):
                raise RuleViolation("A contact needs a phone number or an email.") from exc
            raise RuleViolation("That contact could not be saved.") from exc


# --- job cards -----------------------------------------------------------------


def create_job_card(
    actor,
    client: Client,
    *,
    dispatch_policy: str | None = None,
    owner_user=None,
    **fields: Any,
) -> JobCard:
    """Open a new enquiry.

    ``dispatch_policy`` is seeded from the client's default when not supplied.
    It is a *copy*: a later change to the client's default leaves this card
    alone, which is the behaviour a dispute over partial shipment depends on.
    """
    require_permission(actor, constants.RES_JOB_CARD, "create")
    _reject_unknown(fields, _JOB_CARD_FIELDS, "job card")
    if "client_contact" in fields:
        fields["client_contact_id"] = fields.pop("client_contact")
    if fields.get("enquiry_source") is None:
        # NOT NULL DEFAULT 'other' — an explicit None in the INSERT overrides
        # the column's own db_default instead of leaving it to apply, so drop
        # the key rather than pass it through. Same shape as client_contact.
        fields.pop("enquiry_source", None)

    if dispatch_policy is None:
        dispatch_policy = client.default_dispatch_policy
    elif dispatch_policy not in DispatchPolicy.values:
        raise RuleViolation(f"{dispatch_policy!r} is not a valid dispatch policy.")

    with audit_actor(actor):
        try:
            return JobCard.objects.create(
                job_no=next_job_no(),
                client=client,
                owner_user=owner_user or actor,
                dispatch_policy=dispatch_policy,
                **fields,
            )
        except IntegrityError as exc:
            if "ck_job_cards_required" in str(exc):
                raise RuleViolation(
                    "The required-by date cannot be before the enquiry date."
                ) from exc
            raise RuleViolation("That job card could not be created.") from exc


_JOB_CARD_FIELDS = frozenset(
    {
        "client_contact",
        "lifecycle_status",
        "enquiry_source",
        "enquiry_date",
        "required_by",
        "requirements",
    }
)


def update_job_card(actor, job_card: JobCard, **fields: Any) -> JobCard:
    require_permission(actor, constants.RES_JOB_CARD, "edit", obj=job_card)
    _reject_unknown(fields, _JOB_CARD_FIELDS | {"dispatch_policy"}, "job card")
    if not fields:
        return job_card

    for name, value in fields.items():
        if name == "client_contact":
            job_card.client_contact_id = value
        elif name == "enquiry_source" and value is None:
            # NOT NULL DEFAULT 'other' — nothing to reset it to over PATCH,
            # so an explicit null leaves the existing value alone rather than
            # sending a NULL the column will reject.
            continue
        else:
            setattr(job_card, name, value)

    with audit_actor(actor):
        try:
            job_card.save(update_fields=sorted(fields))
        except IntegrityError as exc:
            raise RuleViolation(f"That job card could not be updated: {exc}") from exc
    return job_card


def cancel_job_card(actor, job_card: JobCard, reason: str) -> JobCard:
    require_permission(actor, constants.RES_JOB_CARD, "cancel", obj=job_card)
    if not (reason or "").strip():
        raise RuleViolation("Cancelling a job card requires a reason.")
    if job_card.lifecycle_status == JobLifecycleStatus.CANCELLED:
        raise RuleViolation("That job card is already cancelled.")

    with audit_actor(actor):
        job_card.lifecycle_status = JobLifecycleStatus.CANCELLED
        job_card.save(update_fields=["lifecycle_status"])
        JobNote.objects.create(
            job_card=job_card, author_user=actor, body=f"Cancelled: {reason.strip()}"
        )
    return job_card


def sync_job_card_status_from_lines(job_card_id) -> None:
    """Keep ``lifecycle_status`` in step with what happened to every line on
    the pipeline board (``Stage.cascades_job_card_status``, pipeline
    migration 0008) — e.g. cancelling a card's only line now marks the card
    Cancelled too, instead of the job cards list still showing "Open" (or
    even "Won") for a card nothing is actually happening on anymore.

    Deliberately has no "never walk back a Won card" guard: a real order
    can be confirmed and later still be cancelled by the client, and that
    must be reflected — a Won card whose lines are all subsequently
    cancelled becomes Cancelled, not left stuck showing Won. The only
    protection is "every active line must agree on the same outcome," so a
    single stray cancellation on an otherwise-live multi-line card never
    cascades.

    A line landing back at the pipeline's initial stage
    (``Stage.is_initial`` — never a hardcoded stage code) is not itself in
    ``cascades_job_card_status`` (that column only covers won/lost/
    cancelled), so it's handled here directly: if the card already has a
    quotation on file, being back at the initial stage means Sales pressed
    "Rework," not that this is a brand-new never-quoted enquiry — the same
    "every active line must agree" rule still gates the cascade.

    Called by ``apps.sales.signals`` after any ``JobLineTransition`` is
    created — no permission check here, since this is a system-derived
    side effect of a transition ``perform_transition()`` already
    authorised, not a new user-initiated action.
    """
    card = JobCard.objects.filter(pk=job_card_id, deleted_at__isnull=True).first()
    if card is None:
        return

    reworked = card.quotations.exists()
    outcomes = {
        cascades or (JobLifecycleStatus.REWORK if is_initial and reworked else None)
        for cascades, is_initial in JobLine.objects.filter(
            job_card_id=job_card_id, deleted_at__isnull=True
        ).values_list("current_stage__cascades_job_card_status", "current_stage__is_initial")
    }
    if len(outcomes) != 1:
        return
    (outcome,) = outcomes
    if outcome is None or outcome == card.lifecycle_status:
        return

    card.lifecycle_status = outcome
    card.save(update_fields=["lifecycle_status"])


# --- job lines -------------------------------------------------------------------


def add_job_line(actor, job_card: JobCard, **fields: Any) -> JobLine:
    """Add a line to a card, at the pipeline's initial stage.

    No transition row is written. ``current_stage_id`` is NOT NULL, so the line
    already sits at the initial stage the moment it exists, and
    ``apply_transition()`` would reject an insert claiming a NULL source stage
    as stale. Entry into the initial stage is recorded by ``created_at``.
    """
    require_permission(actor, constants.RES_JOB_LINE, "create", obj=job_card)
    _reject_unknown(fields, _JOB_LINE_FIELDS, "job line")

    stage = initial_stage()
    if stage is None:
        from apps.core.exceptions import ConfigurationError

        raise ConfigurationError(
            "The pipeline has no active initial stage, so a job line cannot be "
            "created. Seed the stage graph before opening work."
        )

    with audit_actor(actor):
        line_no = fields.pop("line_no", None) or _next_line_no(job_card)
        try:
            return JobLine.objects.create(
                job_card=job_card, line_no=line_no, current_stage=stage, **fields
            )
        except IntegrityError as exc:
            if "uk_job_lines_line_no" in str(exc):
                raise RuleViolation(f"Line {line_no} already exists on this card.") from exc
            if "ck_job_lines_quantity" in str(exc):
                raise RuleViolation("Quantity must be greater than zero.") from exc
            raise RuleViolation("That job line could not be added.") from exc


_JOB_LINE_FIELDS = frozenset(
    {
        "line_no",
        "product_category",
        "description",
        "quantity",
        "line_status",
        "required_by",
        "specs",
    }
)


def _next_line_no(job_card: JobCard) -> int:
    highest = JobLine.objects.filter(job_card=job_card).aggregate(Max("line_no"))[
        "line_no__max"
    ]
    return (highest or 0) + 1


def update_job_line(actor, job_line: JobLine, **fields: Any) -> JobLine:
    require_permission(actor, constants.RES_JOB_LINE, "edit", obj=job_line)
    # current_stage is deliberately absent from the writable set: it belongs to
    # the apply_transition() trigger, and assigning it here would desynchronise
    # the pointer from the transition history.
    _reject_unknown(fields, _JOB_LINE_FIELDS - {"line_no"}, "job line")
    if not fields:
        return job_line

    for name, value in fields.items():
        setattr(job_line, name, value)

    with audit_actor(actor):
        try:
            job_line.save(update_fields=sorted(fields))
        except IntegrityError as exc:
            raise RuleViolation(f"That job line could not be updated: {exc}") from exc
    return job_line


# --- quotations ----------------------------------------------------------------------


def current_quotation(job_card: JobCard) -> Quotation | None:
    """The revision that currently counts — the one not yet superseded.

    At most one such row per card: ``create_quotation_revision`` always
    supersedes whatever was current the moment it inserts the next one.
    """
    return (
        Quotation.objects.filter(job_card=job_card, status=QuotationStatus.DRAFT)
        .order_by("-revision_no")
        .first()
    )


def create_quotation_revision(
    actor,
    job_card: JobCard,
    *,
    pdf: UploadedFile,
    quoted_amount: Decimal | None = None,
    valid_till=None,
    job_lines: list[JobLine] | None = None,
    line_amounts: dict | None = None,
) -> Quotation:
    """Draft the next revision, superseding whatever is current.

    The chain stays linear because ``uk_quotations_supersedes`` is UNIQUE: two
    revisions cannot claim the same predecessor. A revision without a PDF
    doesn't fit this system's actual process — ACCT's whole action *is*
    attaching the priced PDF — so ``pdf`` is required, not optional.
    """
    require_permission(actor, constants.RES_QUOTATION, "create", obj=job_card)

    if pdf is None:
        raise RuleViolation("A quotation revision needs a PDF attached.")

    with audit_actor(actor):
        previous = (
            Quotation.objects.select_for_update()
            .filter(job_card=job_card)
            .order_by("-revision_no")
            .first()
        )

        if pdf.size is not None and pdf.size > settings.QUOTATION_PDF_MAX_BYTES:
            raise RuleViolation(
                f"Quotation PDF is {pdf.size} bytes; the limit is "
                f"{settings.QUOTATION_PDF_MAX_BYTES} bytes (5MB).",
                byte_size=pdf.size,
                limit=settings.QUOTATION_PDF_MAX_BYTES,
            )
        document = upload_document(actor, pdf)

        if previous is not None:
            previous.status = QuotationStatus.SUPERSEDED
            previous.save(update_fields=["status"])

        try:
            quotation = Quotation.objects.create(
                quotation_no=next_quotation_no(),
                job_card=job_card,
                revision_no=(previous.revision_no + 1) if previous else 0,
                supersedes=previous,
                status=QuotationStatus.DRAFT,
                quoted_amount=quoted_amount,
                valid_till=valid_till,
                pdf_document=document,
                prepared_by=actor,
            )
        except IntegrityError as exc:
            raise RuleViolation(f"That revision could not be created: {exc}") from exc

        # The PDF's arrival is the real signal in this system's actual
        # process — no separate "send" step exists. Advance any line still
        # at ENQUIRY (same as before), and advance the card itself the way
        # send_quotation() used to: only from OPEN or REWORK, never walking
        # back a card already further along (quoted/won/lost/cancelled).
        _advance_lines_on_quotation_pdf(actor, job_card)
        if job_card.lifecycle_status in (
            JobLifecycleStatus.OPEN,
            JobLifecycleStatus.REWORK,
        ):
            job_card.lifecycle_status = JobLifecycleStatus.QUOTED
            job_card.save(update_fields=["lifecycle_status"])

        return quotation


def _advance_lines_on_quotation_pdf(actor, job_card: JobCard) -> None:
    """Advance every line still at ENQUIRY to QUOTATION now that a PDF is
    attached, through the same perform_transition() a manual "quote" click
    uses — no bypass of role/staleness checks, no stage code compared as a
    literal.

    A line the actor's role has no "quote" rule for (wrong stage, or a role
    that doesn't hold it) is not an error here: PermissionDenied just means
    this particular line isn't eligible — most commonly because it is
    already at QUOTATION, which is exactly where it needs to be — and the
    quotation upload that triggered this must still succeed regardless.
    """
    for line in sales_selectors.lines_for(job_card):
        try:
            perform_transition(actor, line, "quote")
        except PermissionDenied:
            continue
        except DomainError:
            logger.warning(
                "Auto-advance to Quotation failed for job line %s after a "
                "quotation PDF was attached.",
                line.pk,
                exc_info=True,
            )


def set_quotation_lines(actor, quotation: Quotation, line_amounts: dict) -> None:
    """Replace the priced lines on a draft revision.

    ``line_amounts`` maps ``JobLine`` to amount. Wholesale replacement rather
    than a diff: a revision prices a specific set of lines, and a partial
    update would leave a revision half describing the previous one.
    """
    require_permission(actor, constants.RES_QUOTATION, "edit", obj=quotation)
    if quotation.status != QuotationStatus.DRAFT:
        raise RuleViolation("Only a draft revision's lines may be changed.")

    with audit_actor(actor):
        QuotationLine.objects.filter(quotation=quotation).delete()
        for job_line, amount in line_amounts.items():
            if job_line.job_card_id != quotation.job_card_id:
                raise RuleViolation(
                    "A quotation may only price lines from its own job card."
                )
            QuotationLine.objects.create(
                quotation=quotation, job_line=job_line, line_amount=amount
            )



# --- notes and attachments -------------------------------------------------------------


def add_note(actor, job_card: JobCard, body: str, job_line: JobLine | None = None) -> JobNote:
    require_permission(actor, constants.RES_JOB_NOTE, "create", obj=job_card)
    if not (body or "").strip():
        raise RuleViolation("A note cannot be empty.")
    if job_line is not None and job_line.job_card_id != job_card.id:
        raise RuleViolation("That job line belongs to a different job card.")

    with audit_actor(actor):
        return JobNote.objects.create(
            job_card=job_card, job_line=job_line, author_user=actor, body=body.strip()
        )


def attach_file(
    actor,
    job_card: JobCard,
    upload: UploadedFile,
    *,
    label: str | None = None,
    job_line: JobLine | None = None,
) -> JobAttachment:
    require_permission(actor, constants.RES_JOB_CARD, "edit", obj=job_card)
    if job_line is not None and job_line.job_card_id != job_card.id:
        raise RuleViolation("That job line belongs to a different job card.")

    document = upload_document(actor, upload)

    with audit_actor(actor):
        try:
            return JobAttachment.objects.create(
                job_card=job_card,
                job_line=job_line,
                document=document,
                label=label,
                attached_by=actor,
            )
        except IntegrityError as exc:
            # uk_job_attachments is (job_card, document). It cannot collide
            # through this path — every call uploads a fresh document — so
            # there is no specific branch for it. The constraint still guards
            # the admin and direct writes.
            raise RuleViolation(f"That file could not be attached: {exc}") from exc


def remove_attachment(actor, job_card: JobCard, attachment: JobAttachment) -> None:
    """Detach a file from a card.

    The underlying ``Document`` (and its bytes in storage) are left alone —
    ``fk("core.Document", models.PROTECT, ...)`` means the database would
    refuse to remove it while any attachment still pointed at it anyway, and
    this system prefers to keep what was uploaded rather than destroy it.
    Only the card's link to it goes away.
    """
    require_permission(actor, constants.RES_JOB_CARD, "edit", obj=job_card)
    if attachment.job_card_id != job_card.id:
        raise RuleViolation("That attachment belongs to a different job card.")

    with audit_actor(actor):
        attachment.delete()


# --- shared -------------------------------------------------------------------------------


def _reject_unknown(fields: dict, allowed: frozenset | set, what: str) -> None:
    unknown = set(fields) - set(allowed)
    if unknown:
        raise RuleViolation(f"Unknown {what} field(s): {', '.join(sorted(unknown))}.")


def get_job_card(job_no: str) -> JobCard:
    card = JobCard.objects.filter(job_no=job_no, deleted_at__isnull=True).first()
    if card is None:
        raise NotFound(f"No job card numbered {job_no}.")
    return card


__all__ = [
    "add_client_contact",
    "add_job_line",
    "add_note",
    "attach_file",
    "cancel_job_card",
    "create_client",
    "create_job_card",
    "create_quotation_revision",
    "current_quotation",
    "get_job_card",
    "remove_attachment",
    "set_quotation_lines",
    "sync_job_card_status_from_lines",
    "transaction",
    "update_client",
    "update_job_card",
    "update_job_line",
]
