"""Sales error paths and the less-travelled branches."""

import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.exceptions import ConfigurationError, NotFound, RuleViolation
from apps.identity import constants
from apps.identity.models import Role
from apps.pipeline.models import Stage
from apps.sales.models import DispatchPolicy, QuotationStatus
from apps.sales.services import (
    add_job_line,
    attach_file,
    cancel_job_card,
    create_client,
    create_job_card,
    create_quotation_revision,
    get_job_card,
    set_quotation_lines,
    update_client,
    update_job_card,
    update_job_line,
)
from tests.factories import (
    ClientFactory,
    ProductCategoryFactory,
    UserAccountFactory,
    UserRoleFactory,
)


def with_role(*codes: str):
    user = UserAccountFactory()
    for code in codes:
        UserRoleFactory(user=user, role=Role.objects.get(code=code))
    return user


@pytest.fixture
def sales(db):
    return with_role(constants.ROLE_SALES)


@pytest.fixture
def owner(db):
    return with_role(constants.ROLE_OWNER)


def a_pdf(name="quote.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 quotation", content_type="application/pdf")


# --- mass-assignment guards ------------------------------------------------------


@pytest.mark.django_db
def test_unknown_client_fields_are_refused(sales):
    with pytest.raises(RuleViolation, match="Unknown client field"):
        create_client(sales, legal_name="X", credit_limit=999999)


@pytest.mark.django_db
def test_unknown_job_card_fields_are_refused(sales):
    with pytest.raises(RuleViolation, match="Unknown job card field"):
        create_job_card(sales, ClientFactory(), secret_discount=90)


@pytest.mark.django_db
def test_an_empty_update_is_a_no_op(sales):
    client = create_client(sales, legal_name="No-op Ltd")
    assert update_client(sales, client) is client

    card = create_job_card(sales, client)
    assert update_job_card(sales, card) is card

    line = add_job_line(
        sales, card, product_category=ProductCategoryFactory(code="NOOPCAT"),
        description="Panel", quantity=1,
    )
    assert update_job_line(sales, line) is line


# --- constraint translations -------------------------------------------------------


@pytest.mark.django_db
def test_a_duplicate_gstin_is_explained(sales):
    create_client(sales, legal_name="First", gstin="27AAPFU0939F1ZV")

    with pytest.raises(RuleViolation, match="already registered"):
        create_client(sales, legal_name="Second", gstin="27AAPFU0939F1ZV")


@pytest.mark.django_db
def test_a_required_by_date_before_the_enquiry_date_is_refused(sales):
    with pytest.raises(RuleViolation, match="required-by date"):
        create_job_card(
            sales,
            ClientFactory(),
            enquiry_date=datetime.date(2026, 6, 1),
            required_by=datetime.date(2026, 1, 1),
        )


@pytest.mark.django_db
def test_an_invalid_dispatch_policy_on_update_is_refused_by_the_check(sales):
    card = create_job_card(sales, ClientFactory())

    with pytest.raises(RuleViolation):
        update_job_card(sales, card, dispatch_policy="sometimes")


@pytest.mark.django_db
def test_the_same_file_uploaded_twice_makes_two_attachments(sales):
    """uk_job_attachments is (job_card, document), and each upload creates its
    own document row — so re-uploading identical bytes is two attachments, not
    a collision. Deduplication is deliberately not attempted."""
    card = create_job_card(sales, ClientFactory())

    first = attach_file(sales, card, a_pdf("drawing.pdf"), label="Rev A")
    second = attach_file(sales, card, a_pdf("drawing.pdf"), label="Rev B")

    assert first.document_id != second.document_id
    assert first.document.sha256 == second.document.sha256


# --- the pipeline has to exist ---------------------------------------------------------


@pytest.mark.django_db
def test_adding_a_line_without_an_initial_stage_is_a_configuration_error(sales):
    """A job line's current_stage_id is NOT NULL, so there is nowhere to put a
    line if the stage graph was never seeded. That is bad configuration, not
    bad input."""
    Stage.objects.filter(is_initial=True).update(is_active=False)
    card = create_job_card(sales, ClientFactory())

    with pytest.raises(ConfigurationError, match="no active initial stage"):
        add_job_line(
            sales, card, product_category=ProductCategoryFactory(code="NOSTAGECAT"),
            description="Panel", quantity=1,
        )


# --- lookups -------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_job_card_finds_by_number(sales):
    card = create_job_card(sales, ClientFactory())
    assert get_job_card(card.job_no) == card


@pytest.mark.django_db
def test_get_job_card_raises_not_found_for_an_unknown_number():
    with pytest.raises(NotFound, match="No job card numbered"):
        get_job_card("JOB-1999-00001")


@pytest.mark.django_db
def test_a_soft_deleted_card_is_not_found(sales):
    from django.utils import timezone

    card = create_job_card(sales, ClientFactory())
    card.deleted_at = timezone.now()
    card.save(update_fields=["deleted_at"])

    with pytest.raises(NotFound):
        get_job_card(card.job_no)


# --- the status machine's remaining edges ------------------------------------------------


@pytest.mark.django_db
def test_lines_cannot_be_set_on_a_non_draft_revision(sales, owner):
    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card, product_category=ProductCategoryFactory(code="LOCKEDCAT"),
        description="Panel", quantity=1,
    )
    quotation = create_quotation_revision(owner, card, pdf=a_pdf())
    create_quotation_revision(owner, card, pdf=a_pdf("rev2.pdf"))
    quotation.refresh_from_db()

    with pytest.raises(RuleViolation, match="Only a draft"):
        set_quotation_lines(sales, quotation, {line: Decimal("500.00")})


@pytest.mark.django_db
def test_cancelling_an_already_cancelled_card_is_refused(sales):
    card = create_job_card(sales, ClientFactory())
    cancel_job_card(sales, card, "First cancellation.")

    with pytest.raises(RuleViolation, match="already cancelled"):
        cancel_job_card(sales, card, "Second cancellation.")


@pytest.mark.django_db
def test_a_quotation_can_be_prepared_for_a_complete_only_card(sales, owner):
    """dispatch_policy does not gate quoting — the convergence rule that reads
    it belongs to the dispatch module and is deliberately not built."""
    client = ClientFactory(default_dispatch_policy=DispatchPolicy.COMPLETE_ONLY)
    card = create_job_card(sales, client)

    quotation = create_quotation_revision(owner, card, pdf=a_pdf())

    assert quotation.status == QuotationStatus.DRAFT
    assert card.dispatch_policy == DispatchPolicy.COMPLETE_ONLY
