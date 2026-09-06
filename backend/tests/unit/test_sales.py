"""Sales: job cards, dispatch policy, and the quotation revision chain."""

import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.exceptions import PermissionDenied, RuleViolation
from apps.core.models import Document
from apps.identity import constants
from apps.identity.models import Role
from apps.pipeline.services import perform_transition
from apps.sales.models import (
    DispatchPolicy,
    JobAttachment,
    JobLifecycleStatus,
    JobNote,
    QuotationLine,
    QuotationStatus,
)
from apps.sales.selectors import latest_quotation_by_card
from apps.sales.services import (
    add_client_contact,
    add_job_line,
    add_note,
    attach_file,
    cancel_job_card,
    create_client,
    create_job_card,
    create_quotation_revision,
    current_quotation,
    remove_attachment,
    set_quotation_lines,
    update_client,
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


# --- clients ---------------------------------------------------------------------


@pytest.mark.django_db
def test_sales_can_create_a_client(sales):
    client = create_client(sales, legal_name="Acme Switchgear Pvt Ltd")

    assert client.created_by_id == sales.id
    assert client.default_dispatch_policy == DispatchPolicy.PARTIAL_ALLOWED
    # client_code is never caller-supplied — the service always issues it.
    assert client.client_code.startswith("CLI-")


@pytest.mark.django_db
def test_a_malformed_gstin_is_explained(sales):
    with pytest.raises(RuleViolation, match="valid 15-character GSTIN"):
        create_client(sales, legal_name="Bad GSTIN Ltd", gstin="NOTAGSTIN12345")


@pytest.mark.django_db
def test_a_duplicate_client_code_is_rejected_by_the_database():
    """create_client auto-generates the code now, so the app layer can never
    collide — uk_clients_code + citext still guard a direct write that
    bypasses the service (admin raw SQL, psql), exercised at the model layer
    like the equivalent hr.Employee test."""
    from django.db import IntegrityError, transaction

    ClientFactory(client_code="CLI-090010")

    with pytest.raises(IntegrityError, match="uk_clients_code"):
        with transaction.atomic():
            ClientFactory(client_code="cli-090010")


@pytest.mark.django_db
def test_a_second_primary_contact_demotes_the_first(sales):
    """uk_client_contacts_primary allows one. Rather than making the caller
    discover that as an IntegrityError, the incumbent is demoted."""
    client = create_client(sales, legal_name="Contacts Ltd")

    first = add_client_contact(sales, client, contact_name="Asha", phone="+919000000001",
                               is_primary=True)
    second = add_client_contact(sales, client, contact_name="Bala", phone="+919000000002",
                                is_primary=True)

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.is_primary is False
    assert second.is_primary is True


@pytest.mark.django_db
def test_a_contact_with_no_phone_or_email_is_refused(sales):
    client = create_client(sales, legal_name="Unreachable Ltd")

    with pytest.raises(RuleViolation, match="phone number or an email"):
        add_client_contact(sales, client, contact_name="Ghost")


# --- job numbering ------------------------------------------------------------------


@pytest.mark.django_db
def test_job_numbers_are_sequential_and_zero_padded(sales):
    client = ClientFactory()
    first = create_job_card(sales, client)
    second = create_job_card(sales, client)

    year = datetime.date.today().year
    assert first.job_no == f"JOB-{year}-00001"
    assert second.job_no == f"JOB-{year}-00002"


@pytest.mark.django_db
def test_quotation_numbers_use_their_own_counter(sales, owner):
    client = ClientFactory()
    card = create_job_card(sales, client)
    quotation = create_quotation_revision(owner, card, pdf=a_pdf())

    year = datetime.date.today().year
    assert card.job_no == f"JOB-{year}-00001"
    assert quotation.quotation_no == f"QT-{year}-00001"


# --- dispatch policy: the three cases the plan requires ---------------------------------


@pytest.mark.django_db
def test_dispatch_policy_is_seeded_from_the_client_default(sales):
    client = ClientFactory(default_dispatch_policy=DispatchPolicy.COMPLETE_ONLY)

    card = create_job_card(sales, client)

    assert card.dispatch_policy == DispatchPolicy.COMPLETE_ONLY


@pytest.mark.django_db
def test_dispatch_policy_can_be_overridden_at_creation(sales):
    client = ClientFactory(default_dispatch_policy=DispatchPolicy.PARTIAL_ALLOWED)

    card = create_job_card(sales, client, dispatch_policy=DispatchPolicy.COMPLETE_ONLY)

    assert card.dispatch_policy == DispatchPolicy.COMPLETE_ONLY
    client.refresh_from_db()
    assert client.default_dispatch_policy == DispatchPolicy.PARTIAL_ALLOWED


@pytest.mark.django_db
def test_changing_the_client_default_does_not_touch_existing_cards(sales):
    """The copy, not reference, rule. If this ever regressed, a change made
    today would silently rewrite what was agreed on orders placed months ago —
    exactly the dispute the audit trigger on this column exists to settle."""
    client = ClientFactory(default_dispatch_policy=DispatchPolicy.PARTIAL_ALLOWED)
    card = create_job_card(sales, client)
    assert card.dispatch_policy == DispatchPolicy.PARTIAL_ALLOWED

    update_client(sales, client, default_dispatch_policy=DispatchPolicy.COMPLETE_ONLY)

    card.refresh_from_db()
    assert card.dispatch_policy == DispatchPolicy.PARTIAL_ALLOWED


@pytest.mark.django_db
def test_an_invalid_dispatch_policy_is_refused(sales):
    with pytest.raises(RuleViolation, match="not a valid dispatch policy"):
        create_job_card(sales, ClientFactory(), dispatch_policy="whenever")


@pytest.mark.django_db
def test_a_mid_order_policy_change_is_audited(sales, db_cursor):
    from apps.sales.services import update_job_card

    card = create_job_card(sales, ClientFactory())
    update_job_card(sales, card, dispatch_policy=DispatchPolicy.COMPLETE_ONLY)

    db_cursor.execute(
        """
        SELECT old_data ->> 'dispatch_policy', new_data ->> 'dispatch_policy', changed_by
        FROM core_audit_logs
        WHERE table_name = 'sales_job_cards' AND operation = 'UPDATE'
        ORDER BY id DESC LIMIT 1
        """
    )
    old, new, changed_by = db_cursor.fetchone()
    assert old == DispatchPolicy.PARTIAL_ALLOWED
    assert new == DispatchPolicy.COMPLETE_ONLY
    assert str(changed_by) == str(sales.id)


# --- job lines -------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_new_line_starts_at_the_initial_stage_with_no_transition_row(sales):
    from apps.pipeline.models import JobLineTransition

    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card, product_category=ProductCategoryFactory(code="LINECAT"),
        description="LT panel", quantity=2,
    )

    assert line.current_stage.code == "ENQUIRY"
    assert line.current_stage.is_initial is True
    # Deliberately none: apply_transition() would reject a NULL from_stage.
    assert JobLineTransition.objects.filter(job_line=line).count() == 0


@pytest.mark.django_db
def test_line_numbers_increment_per_card(sales):
    card = create_job_card(sales, ClientFactory())
    category = ProductCategoryFactory(code="SEQCAT")

    first = add_job_line(sales, card, product_category=category, description="A", quantity=1)
    second = add_job_line(sales, card, product_category=category, description="B", quantity=1)

    assert (first.line_no, second.line_no) == (1, 2)


@pytest.mark.django_db
def test_a_duplicate_line_number_is_explained(sales):
    card = create_job_card(sales, ClientFactory())
    category = ProductCategoryFactory(code="DUPLINECAT")
    add_job_line(sales, card, product_category=category, description="A", quantity=1, line_no=1)

    with pytest.raises(RuleViolation, match="already exists"):
        add_job_line(
            sales, card, product_category=category, description="B", quantity=1, line_no=1
        )


@pytest.mark.django_db
def test_zero_quantity_is_refused(sales):
    card = create_job_card(sales, ClientFactory())

    with pytest.raises(RuleViolation, match="greater than zero"):
        add_job_line(
            sales, card, product_category=ProductCategoryFactory(code="ZEROCAT"),
            description="Nothing", quantity=0,
        )


@pytest.mark.django_db
def test_current_stage_cannot_be_written_through_the_service(sales):
    from apps.sales.services import update_job_line

    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card, product_category=ProductCategoryFactory(code="STAGECAT"),
        description="Panel", quantity=1,
    )

    with pytest.raises(RuleViolation, match="Unknown job line field"):
        update_job_line(sales, line, current_stage=None)


# --- the quotation revision chain -----------------------------------------------------------


@pytest.mark.django_db
def test_the_first_revision_is_zero(sales, owner):
    card = create_job_card(sales, ClientFactory())
    quotation = create_quotation_revision(
        owner, card, pdf=a_pdf(), quoted_amount=Decimal("125000.00")
    )

    assert quotation.revision_no == 0
    assert quotation.supersedes_id is None
    assert quotation.status == QuotationStatus.DRAFT


@pytest.mark.django_db
def test_a_revision_supersedes_its_predecessor_and_the_chain_stays_linear(sales, owner):
    card = create_job_card(sales, ClientFactory())
    first = create_quotation_revision(owner, card, pdf=a_pdf())

    second = create_quotation_revision(owner, card, pdf=a_pdf("rev2.pdf"))

    first.refresh_from_db()
    assert second.revision_no == 1
    assert second.supersedes_id == first.id
    assert first.status == QuotationStatus.SUPERSEDED


@pytest.mark.django_db
def test_uploading_a_revision_after_rework_marks_the_card_quoted_again(sales, owner):
    card = create_job_card(sales, ClientFactory())
    line = add_job_line(
        sales, card,
        product_category=ProductCategoryFactory(code="REWORKREQUOTECAT"),
        description="Panel", quantity=1,
    )
    create_quotation_revision(owner, card, pdf=a_pdf())
    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.QUOTED
    line.refresh_from_db()
    perform_transition(sales, line, "rework", note="Client asked for changes.")
    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.REWORK

    create_quotation_revision(owner, card, pdf=a_pdf("rev2.pdf"))

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.QUOTED


@pytest.mark.django_db
def test_a_revision_without_a_pdf_is_refused(sales, owner):
    """A revision without a PDF doesn't fit this system's actual process —
    ACCT's whole action is attaching the priced PDF."""
    card = create_job_card(sales, ClientFactory())

    with pytest.raises(RuleViolation, match="needs a PDF attached"):
        create_quotation_revision(owner, card, pdf=None)


@pytest.mark.django_db
def test_a_new_revision_is_always_uploadable_regardless_of_prior_state(sales, owner):
    """No more terminal block — a card can be reworked and requoted any
    number of times."""
    card = create_job_card(sales, ClientFactory())
    first = create_quotation_revision(owner, card, pdf=a_pdf())
    second = create_quotation_revision(owner, card, pdf=a_pdf("rev2.pdf"))

    third = create_quotation_revision(owner, card, pdf=a_pdf("rev3.pdf"))

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == QuotationStatus.SUPERSEDED
    assert second.status == QuotationStatus.SUPERSEDED
    assert third.status == QuotationStatus.DRAFT


@pytest.mark.django_db
def test_quotation_lines_may_only_price_lines_from_their_own_card(sales, owner):
    card = create_job_card(sales, ClientFactory())
    other = create_job_card(sales, ClientFactory())
    category = ProductCategoryFactory(code="XCARDCAT")
    foreign = add_job_line(
        sales, other, product_category=category, description="Elsewhere", quantity=1
    )
    quotation = create_quotation_revision(owner, card, pdf=a_pdf())

    with pytest.raises(RuleViolation, match="its own job card"):
        set_quotation_lines(sales, quotation, {foreign: Decimal("100.00")})


@pytest.mark.django_db
def test_setting_lines_replaces_rather_than_merges(sales, owner):
    card = create_job_card(sales, ClientFactory())
    category = ProductCategoryFactory(code="REPLACECAT")
    a = add_job_line(sales, card, product_category=category, description="A", quantity=1)
    b = add_job_line(sales, card, product_category=category, description="B", quantity=1)
    quotation = create_quotation_revision(owner, card, pdf=a_pdf())

    set_quotation_lines(sales, quotation, {a: Decimal("100.00"), b: Decimal("200.00")})
    assert QuotationLine.objects.filter(quotation=quotation).count() == 2

    set_quotation_lines(sales, quotation, {a: Decimal("150.00")})
    remaining = QuotationLine.objects.filter(quotation=quotation)
    assert remaining.count() == 1
    assert remaining.first().line_amount == Decimal("150.00")


@pytest.mark.django_db
def test_latest_quotation_by_card_follows_the_highest_revision(sales, owner):
    """A quotation is created against the whole card, not specific lines —
    the real upload flow never populates QuotationLine (see
    NewRevisionDialog.tsx's docstring). So this selector must key off
    job_card_id, and every line on a card shares its highest-revision
    quotation regardless of that revision's status."""
    card = create_job_card(sales, ClientFactory())
    category = ProductCategoryFactory(code="LATESTQCAT")
    add_job_line(sales, card, product_category=category, description="A", quantity=1)
    add_job_line(sales, card, product_category=category, description="B", quantity=1)

    first = create_quotation_revision(owner, card, pdf=a_pdf())
    second = create_quotation_revision(owner, card, pdf=a_pdf("rev2.pdf"))
    first.refresh_from_db()

    assert first.status == QuotationStatus.SUPERSEDED
    assert second.status == QuotationStatus.DRAFT
    expected = {
        card.id: {
            "quotation_no": second.quotation_no,
            "revision_no": 1,
            "status": QuotationStatus.DRAFT,
        }
    }
    assert latest_quotation_by_card([card.id]) == expected


@pytest.mark.django_db
def test_current_quotation_follows_the_draft_revision(sales, owner):
    card = create_job_card(sales, ClientFactory())
    quotation = create_quotation_revision(owner, card, pdf=a_pdf())

    assert current_quotation(card) == quotation


@pytest.mark.django_db
def test_a_superseded_revision_is_no_longer_current(sales, owner):
    card = create_job_card(sales, ClientFactory())
    create_quotation_revision(owner, card, pdf=a_pdf())
    second = create_quotation_revision(owner, card, pdf=a_pdf("rev2.pdf"))

    assert current_quotation(card) == second


@pytest.mark.django_db
def test_uploading_a_revision_marks_the_card_quoted(sales, owner):
    card = create_job_card(sales, ClientFactory())
    create_quotation_revision(owner, card, pdf=a_pdf())

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.QUOTED


@pytest.mark.django_db
def test_uploading_a_revision_does_not_walk_back_a_card_already_won(sales, owner):
    card = create_job_card(sales, ClientFactory())
    card.lifecycle_status = JobLifecycleStatus.WON
    card.save(update_fields=["lifecycle_status"])

    create_quotation_revision(owner, card, pdf=a_pdf())

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.WON


# --- notes, attachments, cancellation ------------------------------------------------------------


@pytest.mark.django_db
def test_a_note_can_be_added_to_a_card(sales):
    card = create_job_card(sales, ClientFactory())
    note = add_note(sales, card, "Client asked for a revised delivery date.")

    assert note.author_user_id == sales.id


@pytest.mark.django_db
def test_an_empty_note_is_refused(sales):
    card = create_job_card(sales, ClientFactory())

    with pytest.raises(RuleViolation, match="cannot be empty"):
        add_note(sales, card, "   ")


@pytest.mark.django_db
def test_a_note_cannot_point_at_another_cards_line(sales):
    card = create_job_card(sales, ClientFactory())
    other = create_job_card(sales, ClientFactory())
    foreign = add_job_line(
        sales, other, product_category=ProductCategoryFactory(code="NOTECAT"),
        description="Elsewhere", quantity=1,
    )

    with pytest.raises(RuleViolation, match="different job card"):
        add_note(sales, card, "Mismatched", job_line=foreign)


@pytest.mark.django_db
def test_a_file_can_be_attached_once(sales):
    card = create_job_card(sales, ClientFactory())
    attachment = attach_file(sales, card, a_pdf("drawing.pdf"), label="Client drawing")

    assert attachment.label == "Client drawing"
    assert attachment.attached_by_id == sales.id


@pytest.mark.django_db
def test_a_file_can_be_removed(sales):
    card = create_job_card(sales, ClientFactory())
    attachment = attach_file(sales, card, a_pdf("drawing.pdf"))

    remove_attachment(sales, card, attachment)

    assert JobAttachment.objects.filter(pk=attachment.pk).count() == 0


@pytest.mark.django_db
def test_removing_an_attachment_leaves_the_document_in_place(sales):
    """The link goes away; the underlying file does not —
    fk("core.Document", models.PROTECT, ...) means the database wouldn't
    allow deleting it anyway, and this system prefers to keep what was
    uploaded rather than destroy it."""
    card = create_job_card(sales, ClientFactory())
    attachment = attach_file(sales, card, a_pdf("drawing.pdf"))
    document_id = attachment.document_id

    remove_attachment(sales, card, attachment)

    assert Document.objects.filter(pk=document_id).exists()


@pytest.mark.django_db
def test_removing_an_attachment_from_the_wrong_card_is_refused(sales):
    card = create_job_card(sales, ClientFactory())
    other_card = create_job_card(sales, ClientFactory())
    attachment = attach_file(sales, card, a_pdf("drawing.pdf"))

    with pytest.raises(RuleViolation, match="different job card"):
        remove_attachment(sales, other_card, attachment)


@pytest.mark.django_db
def test_cancelling_a_card_records_the_reason_as_a_note(sales):
    card = create_job_card(sales, ClientFactory())

    cancel_job_card(sales, card, "Client went with another supplier.")

    card.refresh_from_db()
    assert card.lifecycle_status == JobLifecycleStatus.CANCELLED
    assert JobNote.objects.filter(job_card=card).count() == 1


@pytest.mark.django_db
def test_cancelling_requires_a_reason(sales):
    card = create_job_card(sales, ClientFactory())

    with pytest.raises(RuleViolation, match="requires a reason"):
        cancel_job_card(sales, card, "")


@pytest.mark.django_db
def test_a_designer_cannot_create_a_job_card(db):
    designer = with_role(constants.ROLE_DESIGN)

    with pytest.raises(PermissionDenied):
        create_job_card(designer, ClientFactory())
