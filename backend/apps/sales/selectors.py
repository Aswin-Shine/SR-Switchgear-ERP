"""Reads for the sales app.

The soft-delete filter is written out at every call site rather than hidden in
a manager, and it matches ``idx_job_cards_open``
(``WHERE deleted_at IS NULL AND lifecycle_status IN ('open','quoted')``) — so
``open_job_cards_for`` is the query that index exists to serve.
"""

from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from apps.sales.models import (
    Client,
    ClientContact,
    JobAttachment,
    JobCard,
    JobLifecycleStatus,
    JobLine,
    JobNote,
    Quotation,
    QuotationLine,
    QuotationStatus,
)

OPEN_STATUSES = (
    JobLifecycleStatus.OPEN,
    JobLifecycleStatus.QUOTED,
    JobLifecycleStatus.REWORK,
)


def live_clients() -> QuerySet[Client]:
    return Client.objects.filter(deleted_at__isnull=True)


def search_clients(term: str = "", *, active_only: bool = False) -> QuerySet[Client]:
    queryset = live_clients()
    if active_only:
        queryset = queryset.filter(is_active=True)
    if term:
        queryset = queryset.filter(
            Q(legal_name__icontains=term)
            | Q(client_code__icontains=term)
            | Q(gstin__icontains=term)
        )
    return queryset.order_by("client_code")


def contacts_for(client: Client) -> QuerySet[ClientContact]:
    return ClientContact.objects.filter(
        client=client, deleted_at__isnull=True
    ).order_by("-is_primary", "contact_name")


def live_job_cards() -> QuerySet[JobCard]:
    return JobCard.objects.filter(deleted_at__isnull=True).select_related(
        "client", "owner_user", "client_contact"
    )


def open_job_cards_for(owner_user=None) -> QuerySet[JobCard]:
    """The per-rep open-jobs list. Matches idx_job_cards_open exactly."""
    queryset = live_job_cards().filter(lifecycle_status__in=OPEN_STATUSES)
    if owner_user is not None:
        queryset = queryset.filter(owner_user=owner_user)
    return queryset.order_by("-enquiry_date")


def search_job_cards(
    term: str = "", *, status: str = "", owner_user=None, client_id=None
) -> QuerySet[JobCard]:
    queryset = live_job_cards()
    if status == "active":
        # Not a real lifecycle_status value — matches open_job_cards_for()'s
        # OPEN_STATUSES exactly, so the list's "Active" filter and the Dashboard's
        # "My open job cards" agree on what "still open" means. Previously the list's
        # default filtered on the literal `open` status alone (freshly-created,
        # unquoted cards only), silently excluding `quoted`/`rework` cards the
        # Dashboard already counted as open — a real, reported inconsistency.
        queryset = queryset.filter(lifecycle_status__in=OPEN_STATUSES)
    elif status:
        queryset = queryset.filter(lifecycle_status=status)
    if owner_user is not None:
        queryset = queryset.filter(owner_user=owner_user)
    if client_id is not None:
        queryset = queryset.filter(client_id=client_id)
    if term:
        queryset = queryset.filter(
            Q(job_no__icontains=term)
            | Q(client__legal_name__icontains=term)
            | Q(client__client_code__icontains=term)
        )
    return queryset.order_by("-enquiry_date", "-job_no")


def lines_for(job_card: JobCard) -> QuerySet[JobLine]:
    return (
        JobLine.objects.filter(job_card=job_card, deleted_at__isnull=True)
        .select_related("product_category", "current_stage")
        .order_by("line_no")
    )


def notes_for(job_card: JobCard) -> QuerySet[JobNote]:
    return (
        JobNote.objects.filter(job_card=job_card)
        .select_related("author_user", "job_line")
        .order_by("-created_at")
    )


def attachments_for(job_card: JobCard) -> QuerySet[JobAttachment]:
    return (
        JobAttachment.objects.filter(job_card=job_card)
        .select_related("document", "attached_by", "job_line")
        .order_by("-attached_at")
    )


def quotations_for(job_card: JobCard) -> QuerySet[Quotation]:
    """Newest revision first, so the current one is at the top."""
    return (
        Quotation.objects.filter(job_card=job_card)
        .select_related("pdf_document", "prepared_by")
        .order_by("-revision_no")
    )


def quotation_lines_for(quotation: Quotation) -> QuerySet[QuotationLine]:
    return (
        QuotationLine.objects.filter(quotation=quotation)
        .select_related("job_line")
        .order_by("job_line__line_no")
    )


def latest_quotation_by_card(job_card_ids) -> dict:
    """``{job_card_id: {"quotation_no", "revision_no", "status"}}`` for the
    highest-revision quotation on each job card.

    A quotation is created against a job card as a whole, not against
    specific lines: the "New revision" upload flow
    (``apps.sales.api.job_card_quotations`` POST) never populates
    ``QuotationLine`` (see ``NewRevisionDialog.tsx``'s docstring — there is
    no covered-lines field to fill in). So every line on a card shares that
    card's current revision; there is no real per-line linkage to join
    through. One query via Postgres ``DISTINCT ON``, same pattern as
    ``apps.pipeline.selectors._last_movers``.
    """
    if not job_card_ids:
        return {}
    rows = (
        Quotation.objects.filter(job_card_id__in=job_card_ids)
        .order_by("job_card_id", "-revision_no")
        .distinct("job_card_id")
    )
    return {
        row.job_card_id: {
            "quotation_no": row.quotation_no,
            "revision_no": row.revision_no,
            "status": row.status,
        }
        for row in rows
    }


def has_quotation_pdf_for_card(job_card_id) -> bool:
    """Whether this job card has ever had a quotation revision with a PDF
    attached. Backs the ``has_quotation_pdf`` name in
    ``apps.pipeline.services.condition_context`` — the "negotiate" transition
    rule requires it, so a line can't reach Negotiation on a card nobody has
    actually quoted."""
    return Quotation.objects.filter(
        job_card_id=job_card_id, pdf_document__isnull=False
    ).exists()


def quotation_pdf_exists_by_card(job_card_ids) -> dict:
    """``{job_card_id: True}`` for every card with at least one quotation
    that has a PDF attached — the bulk form of ``has_quotation_pdf_for_card``,
    one query for the whole board rather than one per line."""
    if not job_card_ids:
        return {}
    ids = (
        Quotation.objects.filter(job_card_id__in=job_card_ids, pdf_document__isnull=False)
        .values_list("job_card_id", flat=True)
        .distinct()
    )
    return dict.fromkeys(ids, True)


def current_quotations_by_card(job_card_ids) -> dict:
    """``{job_card_id: Quotation}`` for the current (not-yet-superseded)
    revision on each card — the bulk form of
    ``apps.sales.services.current_quotation``, same ``status=DRAFT``
    semantic, one query instead of one per card. Backs the Google Sheets
    ledger export, which reads every job card at once."""
    if not job_card_ids:
        return {}
    rows = (
        Quotation.objects.filter(job_card_id__in=job_card_ids, status=QuotationStatus.DRAFT)
        .select_related("pdf_document")
        .order_by("job_card_id", "-revision_no")
        .distinct("job_card_id")
    )
    return {row.job_card_id: row for row in rows}


def attachment_filenames_by_card(job_card_ids) -> dict:
    """``{job_card_id: [(filename, attached_at), ...]}``, newest first.
    ``JobAttachment`` has no ``deleted_at`` — it isn't soft-deleted, unlike
    everything else in this module — so no extra filter is needed beyond
    the FK. Backs the Google Sheets ledger export."""
    if not job_card_ids:
        return {}
    rows = (
        JobAttachment.objects.filter(job_card_id__in=job_card_ids)
        .select_related("document")
        .order_by("job_card_id", "-attached_at")
    )
    out: dict = {}
    for row in rows:
        filename = row.document.original_filename
        out.setdefault(row.job_card_id, []).append((filename, row.attached_at))
    return out


def job_card_export_rows() -> list[dict]:
    """One flat dict per job card, for the Google Sheets ledger export
    (``apps.core.sheets`` / the ``sync_job_sheet`` management command).

    Deliberately unfiltered by status — this is a bookkeeping ledger of
    every non-deleted card, not an "active work" view.
    """
    cards = list(live_job_cards().order_by("job_no"))
    card_ids = [card.id for card in cards]
    quotations = current_quotations_by_card(card_ids)
    attachments = attachment_filenames_by_card(card_ids)
    line_counts = dict(
        JobLine.objects.filter(job_card_id__in=card_ids, deleted_at__isnull=True)
        .values_list("job_card_id")
        .annotate(n=Count("id"))
        .values_list("job_card_id", "n")
    )

    rows = []
    for card in cards:
        quotation = quotations.get(card.id)
        card_attachments = attachments.get(card.id, [])

        quotation_pdf_filename = ""
        if quotation is not None and quotation.pdf_document_id:
            quotation_pdf_filename = quotation.pdf_document.original_filename

        rows.append(
            {
                "job_no": card.job_no,
                "client_legal_name": card.client.legal_name,
                "client_code": card.client.client_code,
                "lifecycle_status": card.lifecycle_status,
                "enquiry_date": card.enquiry_date,
                "required_by": card.required_by,
                "owner_username": card.owner_user.username,
                "line_count": line_counts.get(card.id, 0),
                "quotation_no": quotation.quotation_no if quotation else "",
                "quotation_revision": quotation.revision_no if quotation else "",
                "quotation_status": quotation.status if quotation else "",
                "quoted_amount": (
                    quotation.quoted_amount
                    if quotation and quotation.quoted_amount is not None
                    else ""
                ),
                "valid_till": quotation.valid_till if quotation else "",
                "quotation_pdf_filename": quotation_pdf_filename,
                "attachment_filenames": "; ".join(name for name, _ in card_attachments),
            }
        )
    return rows


_SHEET_HEADERS = [
    "Job No",
    "Client",
    "Client Code",
    "Status",
    "Enquiry Date",
    "Required By",
    "Sales Rep",
    "Lines",
    "Quotation No",
    "Quotation Rev",
    "Quotation Status",
    "Quoted Amount",
    "Valid Till",
    "Quotation PDF",
    "Attachments",
]


def _sheet_cell(value) -> str:
    """Every gspread cell is a JSON-primitive string — dates, Decimals, and
    None all need to become plain text, not left as Python objects."""
    if value is None or value == "":
        return ""
    return str(value)


def job_card_sheet_rows() -> tuple[list[str], list[list[str]]]:
    """``(headers, rows)``, shaped for ``apps.core.sheets.sync_rows`` straight from
    ``job_card_export_rows()``. The one place the ledger's column order and cell
    formatting are defined, so the scheduled ``sync_job_sheet`` command and the
    manual "Sync now" endpoint (``apps.sales.api.sync_job_sheet``) can never
    format the sheet differently from each other."""
    rows = [
        [
            _sheet_cell(data["job_no"]),
            _sheet_cell(data["client_legal_name"]),
            _sheet_cell(data["client_code"]),
            _sheet_cell(data["lifecycle_status"]).replace("_", " ").title(),
            _sheet_cell(data["enquiry_date"]),
            _sheet_cell(data["required_by"]),
            _sheet_cell(data["owner_username"]),
            _sheet_cell(data["line_count"]),
            _sheet_cell(data["quotation_no"]),
            _sheet_cell(data["quotation_revision"]),
            _sheet_cell(data["quotation_status"]).replace("_", " ").title(),
            _sheet_cell(data["quoted_amount"]),
            _sheet_cell(data["valid_till"]),
            _sheet_cell(data["quotation_pdf_filename"]),
            _sheet_cell(data["attachment_filenames"]),
        ]
        for data in job_card_export_rows()
    ]
    return _SHEET_HEADERS, rows
