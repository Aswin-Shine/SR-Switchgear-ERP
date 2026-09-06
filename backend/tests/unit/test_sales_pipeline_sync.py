"""apps.sales.signals: pipeline board actions cascade into job_card.lifecycle_status.

Pipeline migration 0008 / apps.sales.services.sync_job_card_status_from_lines.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.identity import constants
from apps.identity.models import Role
from apps.pipeline.services import perform_transition
from apps.sales.models import JobLifecycleStatus
from apps.sales.services import (
    add_job_line,
    create_job_card,
    create_quotation_revision,
    sync_job_card_status_from_lines,
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


def a_pdf(name="quote.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 quotation", content_type="application/pdf")


@pytest.fixture
def sales(db):
    return with_role(constants.ROLE_SALES)


@pytest.fixture
def owner(db):
    return with_role(constants.ROLE_OWNER)


@pytest.mark.django_db
def test_cancelling_a_cards_only_line_marks_the_card_cancelled(sales):
    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card,
        product_category=ProductCategoryFactory(code="SYNCCANCELCAT"),
        description="Panel", quantity=1,
    )

    perform_transition(sales, line, "cancel", note="Client withdrew.")

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.CANCELLED


@pytest.mark.django_db
def test_cancelling_one_of_two_lines_does_not_cascade(sales):
    card = create_job_card(sales, ClientFactory())
    category = ProductCategoryFactory(code="SYNCPARTIALCAT")
    add_job_line(sales, card, product_category=category, description="Stays open", quantity=1)
    to_cancel = add_job_line(
        sales, card, product_category=category, description="Dropped", quantity=1
    )

    perform_transition(sales, to_cancel, "cancel", note="One panel dropped.")

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.OPEN


@pytest.mark.django_db
def test_losing_a_line_marks_the_card_lost(sales):
    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card,
        product_category=ProductCategoryFactory(code="SYNCLOSTCAT"),
        description="Panel", quantity=1,
    )
    perform_transition(sales, line, "quote")

    perform_transition(sales, line, "lose", note="Client went with a competitor.")

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.LOST


@pytest.mark.django_db
def test_a_won_card_is_moved_to_cancelled_if_its_line_is_later_cancelled(sales):
    """A confirmed order can still fall through after the fact — the client
    cancels a Won job — and the card must reflect that, not stay stuck
    showing Won."""
    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card,
        product_category=ProductCategoryFactory(code="SYNCWONCAT"),
        description="Panel", quantity=1,
    )
    card.lifecycle_status = JobLifecycleStatus.WON
    card.save(update_fields=["lifecycle_status"])

    perform_transition(sales, line, "cancel", note="Client cancelled after confirming.")

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.CANCELLED


@pytest.mark.django_db
def test_a_won_card_with_one_of_two_lines_cancelled_stays_won(sales):
    """The "every line must agree" rule is still the only protection —
    a single stray cancellation on an otherwise-live multi-line Won card
    must not cascade."""
    card = create_job_card(sales, ClientFactory())
    category = ProductCategoryFactory(code="SYNCWONPARTIALCAT")
    add_job_line(sales, card, product_category=category, description="Still live", quantity=1)
    to_cancel = add_job_line(
        sales, card, product_category=category, description="Dropped", quantity=1
    )
    card.lifecycle_status = JobLifecycleStatus.WON
    card.save(update_fields=["lifecycle_status"])

    perform_transition(sales, to_cancel, "cancel", note="One panel dropped.")

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.WON


@pytest.mark.django_db
def test_sync_is_a_noop_once_already_at_the_target_status(sales):
    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card,
        product_category=ProductCategoryFactory(code="SYNCNOOPCAT"),
        description="Panel", quantity=1,
    )
    perform_transition(sales, line, "cancel", note="Client withdrew.")
    card.refresh_from_db()
    updated_at = card.updated_at

    sync_job_card_status_from_lines(card.id)

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.CANCELLED
    assert card.updated_at == updated_at


@pytest.mark.django_db
def test_reworking_a_quoted_lines_only_line_marks_the_card_rework(sales, owner):
    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card,
        product_category=ProductCategoryFactory(code="SYNCREWORKCAT"),
        description="Panel", quantity=1,
    )
    create_quotation_revision(owner, card, pdf=a_pdf())
    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.QUOTED
    line.refresh_from_db()

    perform_transition(sales, line, "rework", note="Client asked for changes.")

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.REWORK


@pytest.mark.django_db
def test_a_reworked_line_with_a_sibling_elsewhere_does_not_cascade(sales, owner):
    """The "every active line must agree" rule is still the only
    protection — a single line kicked back to rework on an otherwise-live
    multi-line card must not cascade, same as the existing partial-cancel
    tests above."""
    card = create_job_card(sales, ClientFactory())
    category = ProductCategoryFactory(code="SYNCREWORKPARTIALCAT")
    add_job_line(sales, card, product_category=category, description="Stays quoted", quantity=1)
    to_rework = add_job_line(
        sales, card, product_category=category, description="Needs changes", quantity=1
    )
    create_quotation_revision(owner, card, pdf=a_pdf())
    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.QUOTED
    to_rework.refresh_from_db()

    perform_transition(sales, to_rework, "rework", note="One panel needs changes.")

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.QUOTED
