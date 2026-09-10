"""``job_card_export_rows()`` — the Google Sheets ledger export's data
assembly. Pure DB reads; no service-layer business rules to exercise, so
these go straight through the factories rather than the create_* services."""

from decimal import Decimal

import pytest

from apps.sales.models import QuotationStatus
from apps.sales.selectors import job_card_export_rows
from tests.factories import JobAttachmentFactory, JobCardFactory, JobLineFactory, QuotationFactory


@pytest.mark.django_db
def test_a_card_with_a_quotation_and_attachments_is_fully_populated():
    card = JobCardFactory()
    JobLineFactory(job_card=card)
    JobLineFactory(job_card=card)
    quotation = QuotationFactory(
        job_card=card, status=QuotationStatus.DRAFT, quoted_amount=Decimal("689000.00")
    )
    JobAttachmentFactory(job_card=card)
    JobAttachmentFactory(job_card=card)

    rows = {row["job_no"]: row for row in job_card_export_rows()}
    row = rows[card.job_no]

    assert row["client_legal_name"] == card.client.legal_name
    assert row["client_code"] == card.client.client_code
    assert row["line_count"] == 2
    assert row["quotation_no"] == quotation.quotation_no
    assert row["quotation_revision"] == quotation.revision_no
    assert row["quoted_amount"] == Decimal("689000.00")
    assert row["quotation_pdf_filename"] == quotation.pdf_document.original_filename
    assert row["attachment_filenames"].count(";") == 1  # two filenames, one separator


@pytest.mark.django_db
def test_a_card_with_no_quotation_renders_blank_not_none():
    card = JobCardFactory()

    row = {r["job_no"]: r for r in job_card_export_rows()}[card.job_no]

    assert row["quotation_no"] == ""
    assert row["quoted_amount"] == ""
    assert row["quotation_pdf_filename"] == ""
    assert row["attachment_filenames"] == ""
    assert row["line_count"] == 0


@pytest.mark.django_db
def test_a_quotation_with_no_amount_or_pdf_renders_blank_not_none():
    card = JobCardFactory()
    QuotationFactory(
        job_card=card, status=QuotationStatus.DRAFT, quoted_amount=None, pdf_document=None
    )

    row = {r["job_no"]: r for r in job_card_export_rows()}[card.job_no]

    assert row["quoted_amount"] == ""
    assert row["quotation_pdf_filename"] == ""


@pytest.mark.django_db
def test_a_superseded_quotation_is_not_the_current_one():
    card = JobCardFactory()
    QuotationFactory(job_card=card, revision_no=0, status=QuotationStatus.SUPERSEDED)
    current = QuotationFactory(job_card=card, revision_no=1, status=QuotationStatus.DRAFT)

    row = {r["job_no"]: r for r in job_card_export_rows()}[card.job_no]

    assert row["quotation_no"] == current.quotation_no
    assert row["quotation_revision"] == 1
