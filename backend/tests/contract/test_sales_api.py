"""Contract tests for the sales endpoints."""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.identity import constants
from apps.identity.models import Role
from apps.sales.models import DispatchPolicy, JobLifecycleStatus, QuotationStatus
from tests.factories import (
    ClientContactFactory,
    ClientFactory,
    JobCardFactory,
    ProductCategoryFactory,
    UserAccountFactory,
    UserRoleFactory,
)

PASSWORD = "a-perfectly-good-password"


def body(response):
    return json.loads(response.content)


def a_pdf(name="quote.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 quotation", content_type="application/pdf")


def with_role(*codes):
    user = UserAccountFactory(password=PASSWORD)
    for code in codes:
        UserRoleFactory(user=user, role=Role.objects.get(code=code))
    return user


@pytest.fixture
def sales(db):
    return with_role(constants.ROLE_SALES)


@pytest.fixture
def signed_in(client, sales):
    client.force_login(sales)
    return client


@pytest.fixture
def owner_client(db, client):
    owner = with_role(constants.ROLE_OWNER)
    client.force_login(owner)
    return client


@pytest.fixture
def accountant(db):
    """Quotation creation moved to ACCT (migration 0007) — SALES no longer
    holds quotation:create. Log this in wherever a test needs to create a
    quotation, then switch back to the `sales` fixture's user if the rest of
    the test needs that identity (e.g. viewing/downloading, still SALES')."""
    return with_role(constants.ROLE_ACCT)


@pytest.fixture
def card(signed_in):
    response = signed_in.post(
        "/api/v1/job-cards",
        data=json.dumps({"client_id": str(ClientFactory().id)}),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    return body(response)


# --- clients -----------------------------------------------------------------------


@pytest.mark.django_db
def test_client_list_is_paginated_with_one_shape(signed_in):
    for n in range(3):
        ClientFactory(client_code=f"PAGE{n}")

    payload = body(signed_in.get("/api/v1/clients?page_size=2"))

    assert set(payload) == {"items", "page", "page_size", "total", "pages"}
    assert len(payload["items"]) == 2
    assert payload["page_size"] == 2


@pytest.mark.django_db
def test_client_payload_shape(signed_in):
    ClientFactory(client_code="SHAPE", legal_name="Shape Ltd")

    item = body(signed_in.get("/api/v1/clients?q=SHAPE"))["items"][0]

    assert set(item) == {
        "id",
        "client_code",
        "legal_name",
        "gstin",
        "billing_city",
        "billing_state",
        "default_dispatch_policy",
        "is_active",
    }


@pytest.mark.django_db
def test_creating_a_client(signed_in):
    response = signed_in.post(
        "/api/v1/clients",
        data=json.dumps({"legal_name": "New Co Pvt Ltd"}),
        content_type="application/json",
    )

    assert response.status_code == 201
    # client_code is never caller-supplied — the server always issues it.
    assert body(response)["client_code"].startswith("CLI-")


@pytest.mark.django_db
def test_a_designer_cannot_create_a_client(client):
    client.force_login(with_role(constants.ROLE_DESIGN))

    response = client.post(
        "/api/v1/clients",
        data=json.dumps({"legal_name": "Nope Ltd"}),
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_an_out_of_range_page_returns_an_empty_list_not_a_404(signed_in):
    ClientFactory(client_code="ONLYONE")

    payload = body(signed_in.get("/api/v1/clients?page=99"))

    assert payload["items"] == []
    assert payload["total"] >= 1


@pytest.mark.django_db
def test_client_detail_includes_contacts(signed_in):
    target = ClientFactory(client_code="WITHCONTACT")
    signed_in.post(
        f"/api/v1/clients/{target.id}/contacts",
        data=json.dumps({"contact_name": "Asha Rao", "phone": "+919000000001",
                         "is_primary": True}),
        content_type="application/json",
    )

    payload = body(signed_in.get(f"/api/v1/clients/{target.id}"))

    assert len(payload["contacts"]) == 1
    assert set(payload["contacts"][0]) == {
        "id", "contact_name", "phone", "email", "is_primary"
    }
    assert payload["contacts"][0]["is_primary"] is True


# --- job cards ------------------------------------------------------------------------


@pytest.mark.django_db
def test_job_card_payload_shape(card):
    assert set(card) == {
        "id",
        "job_no",
        "client",
        "client_contact",
        "owner_user",
        "lifecycle_status",
        "enquiry_source",
        "dispatch_policy",
        "enquiry_date",
        "required_by",
        "requirements",
    }


@pytest.mark.django_db
def test_a_created_card_gets_a_job_number_and_the_clients_dispatch_policy(signed_in):
    target = ClientFactory(
        client_code="POLICYCO", default_dispatch_policy=DispatchPolicy.COMPLETE_ONLY
    )

    payload = body(
        signed_in.post(
            "/api/v1/job-cards",
            data=json.dumps({"client_id": str(target.id)}),
            content_type="application/json",
        )
    )

    assert payload["job_no"].startswith("JOB-")
    assert payload["dispatch_policy"] == DispatchPolicy.COMPLETE_ONLY


@pytest.mark.django_db
def test_sales_cannot_see_another_reps_job_card(signed_in, card):
    """Prevents client poaching between reps (migration 0008): the job-cards
    list only returns the actor's own cards, and another rep's card 403s on
    direct access even by id."""
    others_card = JobCardFactory(owner_user=UserAccountFactory(), client=ClientFactory())

    listed = body(signed_in.get("/api/v1/job-cards"))
    listed_ids = {item["id"] for item in listed["items"]}
    assert card["id"] in listed_ids
    assert str(others_card.id) not in listed_ids

    response = signed_in.get(f"/api/v1/job-cards/{others_card.id}")
    assert response.status_code == 403


@pytest.mark.django_db
def test_the_active_status_filter_matches_the_dashboards_definition_of_open(signed_in, sales, card):
    """The list's "Active" filter and the Dashboard's "My open job cards" must agree —
    previously the list's default filtered on the literal `open` status alone, silently
    excluding `quoted`/`rework` cards the Dashboard already counted as open."""
    quoted = JobCardFactory(owner_user=sales, lifecycle_status=JobLifecycleStatus.QUOTED)
    rework = JobCardFactory(owner_user=sales, lifecycle_status=JobLifecycleStatus.REWORK)
    won = JobCardFactory(owner_user=sales, lifecycle_status=JobLifecycleStatus.WON)

    listed = body(signed_in.get("/api/v1/job-cards?status=active"))
    listed_ids = {item["id"] for item in listed["items"]}

    assert card["id"] in listed_ids  # freshly created -> lifecycle_status=open
    assert str(quoted.id) in listed_ids
    assert str(rework.id) in listed_ids
    assert str(won.id) not in listed_ids

    literal_open = body(signed_in.get("/api/v1/job-cards?status=open"))
    literal_open_ids = {item["id"] for item in literal_open["items"]}
    assert card["id"] in literal_open_ids
    assert str(quoted.id) not in literal_open_ids


@pytest.mark.django_db
def test_dispatch_policy_can_be_overridden_over_the_api(signed_in):
    target = ClientFactory(
        client_code="OVERRIDECO", default_dispatch_policy=DispatchPolicy.PARTIAL_ALLOWED
    )

    payload = body(
        signed_in.post(
            "/api/v1/job-cards",
            data=json.dumps(
                {"client_id": str(target.id), "dispatch_policy": DispatchPolicy.COMPLETE_ONLY}
            ),
            content_type="application/json",
        )
    )

    assert payload["dispatch_policy"] == DispatchPolicy.COMPLETE_ONLY


@pytest.mark.django_db
def test_an_explicit_null_enquiry_source_falls_back_to_the_column_default(signed_in):
    """The frontend's "Not recorded" option sends enquiry_source: null, not an
    omitted key — an explicit None must not override NOT NULL DEFAULT 'other'."""
    target = ClientFactory(client_code="SOURCENULLCO")

    response = signed_in.post(
        "/api/v1/job-cards",
        data=json.dumps({"client_id": str(target.id), "enquiry_source": None}),
        content_type="application/json",
    )

    assert response.status_code == 201
    assert body(response)["enquiry_source"] == "other"


@pytest.mark.django_db
def test_a_card_can_be_created_with_a_client_contact(signed_in):
    """The wire field is `client_contact` (a raw id), not `client_contact_id` —
    it must resolve to a real ClientContact on the created row, not 500 on a
    bare FK assignment."""
    target = ClientFactory(client_code="CONTACTCO")
    contact = ClientContactFactory(client=target)

    payload = body(
        signed_in.post(
            "/api/v1/job-cards",
            data=json.dumps({"client_id": str(target.id), "client_contact": str(contact.id)}),
            content_type="application/json",
        )
    )

    assert payload["client_contact"]["id"] == str(contact.id)


@pytest.mark.django_db
def test_a_cards_client_contact_can_be_set_over_patch(signed_in, card):
    contact = ClientContactFactory(client_id=card["client"]["id"])

    response = signed_in.patch(
        f"/api/v1/job-cards/{card['id']}",
        data=json.dumps({"client_contact": str(contact.id)}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert body(response)["client_contact"]["id"] == str(contact.id)


@pytest.mark.django_db
def test_job_card_detail_includes_lines_and_quotations(signed_in, card):
    payload = body(signed_in.get(f"/api/v1/job-cards/{card['id']}"))

    assert {"lines", "quotations", "current_quotation_id"} <= set(payload)
    assert payload["lines"] == []
    assert payload["current_quotation_id"] is None


@pytest.mark.django_db
def test_cancelling_a_card_requires_a_reason(signed_in, card):
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/cancel",
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert body(response)["error"]["context"]["missing"] == ["reason"]


@pytest.mark.django_db
def test_cancelling_a_card(signed_in, card):
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/cancel",
        data=json.dumps({"reason": "Client withdrew."}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert body(response)["lifecycle_status"] == JobLifecycleStatus.CANCELLED


# --- job lines --------------------------------------------------------------------------


@pytest.mark.django_db
def test_adding_a_line_puts_it_at_the_initial_stage(signed_in, card):
    category = ProductCategoryFactory(code="APILINECAT")

    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/lines",
        data=json.dumps(
            {
                "product_category_id": str(category.id),
                "description": "LT distribution panel",
                "quantity": 3,
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = body(response)
    assert payload["current_stage"]["code"] == "ENQUIRY"
    assert payload["line_no"] == 1
    assert set(payload) == {
        "id",
        "line_no",
        "product_category",
        "description",
        "quantity",
        "line_status",
        "required_by",
        "specs",
        "current_stage",
    }


@pytest.mark.django_db
def test_a_line_cannot_have_its_stage_set_over_the_api(signed_in, card):
    category = ProductCategoryFactory(code="APISTAGECAT")
    line = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/lines",
            data=json.dumps(
                {"product_category_id": str(category.id), "description": "Panel"}
            ),
            content_type="application/json",
        )
    )

    response = signed_in.patch(
        f"/api/v1/job-lines/{line['id']}/edit",
        data=json.dumps({"current_stage": None}),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert "Unknown job line field" in body(response)["error"]["message"]


@pytest.mark.django_db
def test_cancelling_a_line_from_the_board_cascades_the_cards_status(signed_in, card):
    """Pipeline migration 0008: a line cancelled through the pipeline board's
    own transition endpoint — not the separate job-cards/cancel action —
    now marks the card Cancelled too."""
    category = ProductCategoryFactory(code="APISYNCCANCELCAT")
    line = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/lines",
            data=json.dumps(
                {"product_category_id": str(category.id), "description": "Panel"}
            ),
            content_type="application/json",
        )
    )

    signed_in.post(
        f"/api/v1/job-lines/{line['id']}/transitions",
        data=json.dumps({"action_code": "cancel", "note": "Client withdrew."}),
        content_type="application/json",
    )

    updated = body(signed_in.get(f"/api/v1/job-cards/{card['id']}"))
    assert updated["lifecycle_status"] == JobLifecycleStatus.CANCELLED


# --- notes and attachments -----------------------------------------------------------------


@pytest.mark.django_db
def test_adding_and_listing_notes(signed_in, card):
    signed_in.post(
        f"/api/v1/job-cards/{card['id']}/notes",
        data=json.dumps({"body": "Client asked about delivery."}),
        content_type="application/json",
    )

    payload = body(signed_in.get(f"/api/v1/job-cards/{card['id']}/notes"))

    assert len(payload["items"]) == 1
    assert set(payload["items"][0]) == {
        "id", "body", "author", "job_line_id", "created_at"
    }


@pytest.mark.django_db
def test_an_empty_note_is_422(signed_in, card):
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/notes",
        data=json.dumps({"body": "   "}),
        content_type="application/json",
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_attaching_a_file_over_multipart(signed_in, card):
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/attachments",
        data={"file": a_pdf("drawing.pdf"), "label": "Client drawing"},
    )

    assert response.status_code == 201
    payload = body(response)
    assert payload["filename"] == "drawing.pdf"
    assert payload["label"] == "Client drawing"
    assert payload["byte_size"] > 0


@pytest.mark.django_db
def test_attaching_with_no_file_is_422(signed_in, card):
    response = signed_in.post(f"/api/v1/job-cards/{card['id']}/attachments", data={})

    assert response.status_code == 422
    assert "field name 'file'" in body(response)["error"]["message"]


@pytest.mark.django_db
def test_removing_an_attachment(signed_in, card):
    attachment = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/attachments", data={"file": a_pdf("drawing.pdf")}
        )
    )

    response = signed_in.delete(
        f"/api/v1/job-cards/{card['id']}/attachments/{attachment['id']}"
    )

    assert response.status_code == 204
    payload = body(signed_in.get(f"/api/v1/job-cards/{card['id']}/attachments"))
    assert payload["items"] == []


@pytest.mark.django_db
def test_removing_an_attachment_under_the_wrong_card_is_404(signed_in, card):
    attachment = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/attachments", data={"file": a_pdf("drawing.pdf")}
        )
    )
    other_card = body(
        signed_in.post(
            "/api/v1/job-cards",
            data=json.dumps({"client_id": str(ClientFactory().id)}),
            content_type="application/json",
        )
    )

    response = signed_in.delete(
        f"/api/v1/job-cards/{other_card['id']}/attachments/{attachment['id']}"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_the_attachment_download_endpoint_redirects_instead_of_proxying_the_bytes(
    signed_in, card
):
    """302 to storage, not a streamed response — same reasoning as the
    quotation PDF endpoint."""
    attachment = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/attachments", data={"file": a_pdf("drawing.pdf")}
        )
    )

    response = signed_in.get(f"/api/v1/attachments/{attachment['id']}/download")

    assert response.status_code == 302
    assert response["Location"]
    assert not response.content


@pytest.mark.django_db
def test_the_attachment_download_endpoint_still_checks_permission(client, card, signed_in):
    """The signed URL is the delivery mechanism, never the authorisation."""
    attachment = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/attachments", data={"file": a_pdf("drawing.pdf")}
        )
    )

    client.force_login(with_role(constants.ROLE_HR))
    response = client.get(f"/api/v1/attachments/{attachment['id']}/download")

    assert response.status_code == 403


# --- quotations ---------------------------------------------------------------------------------


@pytest.mark.django_db
def test_creating_a_revision_by_multipart_upload(signed_in, card, accountant):
    signed_in.force_login(accountant)
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": a_pdf(), "quoted_amount": "125000.00"},
    )

    assert response.status_code == 201
    payload = body(response)
    assert set(payload) == {
        "id",
        "quotation_no",
        "revision_no",
        "status",
        "supersedes_id",
        "quoted_amount",
        "currency",
        "valid_till",
        "has_pdf",
        "prepared_by",
    }
    assert payload["revision_no"] == 0
    assert payload["status"] == QuotationStatus.DRAFT
    assert payload["has_pdf"] is True


@pytest.mark.django_db
def test_creating_a_revision_with_valid_till_does_not_500(signed_in, card, accountant):
    """Regression: valid_till arrives as a raw form string; the response used
    to crash serialising it back (AttributeError: 'str' object has no
    attribute 'isoformat') because the in-memory object never picked up the
    DB's typed value after create()."""
    signed_in.force_login(accountant)
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": a_pdf(), "quoted_amount": "125000.00", "valid_till": "2026-11-09"},
    )

    assert response.status_code == 201
    assert body(response)["valid_till"] == "2026-11-09"


@pytest.mark.django_db
def test_accounts_role_can_attach_a_quotation_pdf(client, card):
    """ACCT holds quotation:create as of migration 0005 — same POST Sales uses."""
    accountant = with_role(constants.ROLE_ACCT)
    client.force_login(accountant)

    response = client.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": a_pdf(), "quoted_amount": "50000.00"},
    )

    assert response.status_code == 201
    assert body(response)["has_pdf"] is True


@pytest.mark.django_db
def test_a_quotation_pdf_over_5mb_is_422(signed_in, card, accountant):
    oversized = SimpleUploadedFile(
        "big.pdf", b"x" * (5 * 1024 * 1024 + 1), content_type="application/pdf"
    )

    signed_in.force_login(accountant)
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": oversized, "quoted_amount": "50000.00"},
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_attaching_a_pdf_auto_advances_a_line_from_enquiry_to_quotation(
    signed_in, card, accountant
):
    """Attaching the actual PDF is the real signal that a line has been
    quoted — no manual "Quote" click needed first (pipeline migration 0006)."""
    category = ProductCategoryFactory(code="ENQADVANCECAT")
    line = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/lines",
            data=json.dumps({"product_category_id": str(category.id), "description": "Panel"}),
            content_type="application/json",
        )
    )

    signed_in.force_login(accountant)
    signed_in.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": a_pdf(), "quoted_amount": "10000.00"},
    )

    updated = body(signed_in.get(f"/api/v1/job-lines/{line['id']}"))
    assert updated["current_stage"]["code"] == "QUOTATION"


@pytest.mark.django_db
def test_accounts_attaching_a_pdf_also_auto_advances_a_line_from_enquiry(client, card):
    """ACCT holds the same "quote" grant as Sales/Owner as of pipeline
    migration 0006 — its own PDF uploads must not silently fail to advance
    the line while Sales's/Owner's do."""
    category = ProductCategoryFactory(code="ACCTENQCAT")
    # `client` is already signed in as the card's owner (the `card` fixture's
    # own `signed_in`) — job_line:view is owner-scoped for SALES, so line
    # creation below needs that same actor, not a fresh SALES user.
    line = body(
        client.post(
            f"/api/v1/job-cards/{card['id']}/lines",
            data=json.dumps({"product_category_id": str(category.id), "description": "Panel"}),
            content_type="application/json",
        )
    )

    accountant = with_role(constants.ROLE_ACCT)
    client.force_login(accountant)
    client.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": a_pdf(), "quoted_amount": "10000.00"},
    )

    updated = body(client.get(f"/api/v1/job-lines/{line['id']}"))
    assert updated["current_stage"]["code"] == "QUOTATION"


@pytest.mark.django_db
def test_attaching_a_pdf_does_not_touch_lines_on_a_different_card(signed_in, card, accountant):
    """The auto-advance is scoped to the job card the quotation was written
    for — an ENQUIRY line on an unrelated card must not move."""
    other_card = body(
        signed_in.post(
            "/api/v1/job-cards",
            data=json.dumps({"client_id": str(ClientFactory().id)}),
            content_type="application/json",
        )
    )
    category = ProductCategoryFactory(code="OTHERCARDCAT")
    other_line = body(
        signed_in.post(
            f"/api/v1/job-cards/{other_card['id']}/lines",
            data=json.dumps({"product_category_id": str(category.id), "description": "Panel"}),
            content_type="application/json",
        )
    )

    signed_in.force_login(accountant)
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": a_pdf(), "quoted_amount": "10000.00"},
    )

    assert response.status_code == 201
    updated = body(signed_in.get(f"/api/v1/job-lines/{other_line['id']}"))
    assert updated["current_stage"]["code"] == "ENQUIRY"


@pytest.mark.django_db
def test_money_crosses_the_wire_as_a_string(signed_in, card, accountant):
    """A NUMERIC(14,2) through a JavaScript float is how 1234567.89 becomes
    1234567.8899999999 on an invoice."""
    signed_in.force_login(accountant)
    payload = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/quotations",
            data={"pdf": a_pdf(), "quoted_amount": "1234567.89"},
        )
    )

    assert payload["quoted_amount"] == "1234567.89"
    assert isinstance(payload["quoted_amount"], str)


@pytest.mark.django_db
def test_a_malformed_amount_is_422(signed_in, card):
    response = signed_in.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": a_pdf(), "quoted_amount": "not-a-number"},
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_the_full_quotation_lifecycle_over_the_api(client, sales, accountant, card):
    """Upload a priced PDF (quotes the card, auto-advances its line to
    QUOTATION) -> press Confirm on the pipeline board (wins the card). No
    activate/send/accept steps — those don't exist in this system's actual
    process."""
    category = ProductCategoryFactory(code="LIFECYCLEAPICAT")
    client.force_login(sales)
    line = body(
        client.post(
            f"/api/v1/job-cards/{card['id']}/lines",
            data=json.dumps({"product_category_id": str(category.id), "description": "Panel"}),
            content_type="application/json",
        )
    )

    # Sales may not create a quotation — that's Accounts'/Owner's job (0007).
    assert (
        client.post(
            f"/api/v1/job-cards/{card['id']}/quotations",
            data={"pdf": a_pdf(), "quoted_amount": "50000.00"},
        ).status_code
        == 403
    )

    client.force_login(accountant)
    created = client.post(
        f"/api/v1/job-cards/{card['id']}/quotations",
        data={"pdf": a_pdf(), "quoted_amount": "50000.00"},
    )
    assert created.status_code == 201
    assert body(created)["status"] == QuotationStatus.DRAFT

    card_after_quote = body(client.get(f"/api/v1/job-cards/{card['id']}"))
    assert card_after_quote["lifecycle_status"] == JobLifecycleStatus.QUOTED

    owner = with_role(constants.ROLE_OWNER)
    client.force_login(owner)
    confirmed = client.post(
        f"/api/v1/job-lines/{line['id']}/transitions",
        data=json.dumps({"action_code": "confirm"}),
        content_type="application/json",
    )
    assert confirmed.status_code == 201

    card_now = body(client.get(f"/api/v1/job-cards/{card['id']}"))
    assert card_now["lifecycle_status"] == JobLifecycleStatus.WON


@pytest.mark.django_db
def test_creating_a_revision_without_a_pdf_is_422(signed_in, card, accountant):
    signed_in.force_login(accountant)
    response = signed_in.post(f"/api/v1/job-cards/{card['id']}/quotations", data={})

    assert response.status_code == 422


@pytest.mark.django_db
def test_the_pdf_endpoint_redirects_instead_of_proxying_the_bytes(signed_in, card, accountant):
    """302 to storage, not a streamed response: a worker relaying a 4MB PDF is
    a worker not serving requests."""
    signed_in.force_login(accountant)
    quotation = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/quotations", data={"pdf": a_pdf()}
        )
    )

    response = signed_in.get(f"/api/v1/quotations/{quotation['id']}/pdf")

    assert response.status_code == 302
    assert response["Location"]
    # The bytes did not come through Django.
    assert not response.content


@pytest.mark.django_db
def test_the_pdf_download_shows_a_client_identifiable_filename(signed_in, card, accountant):
    """The redirect target's filename must say which job card and revision
    this is — not the quotation number (meaningless to the client) or the
    storage-key UUID."""
    signed_in.force_login(accountant)
    quotation = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/quotations", data={"pdf": a_pdf()}
        )
    )

    response = signed_in.get(f"/api/v1/quotations/{quotation['id']}/pdf")
    assert card["job_no"] in response["Location"]
    # get_valid_filename() turns the space in "Rev 0" into an underscore.
    assert f"Rev_{quotation['revision_no']}" in response["Location"]

    download = signed_in.get(response["Location"])
    assert card["job_no"] in download["Content-Disposition"]
    assert f"Rev_{quotation['revision_no']}" in download["Content-Disposition"]


@pytest.mark.django_db
def test_the_pdf_endpoint_still_checks_permission(client, card, signed_in, accountant):
    """The signed URL is the delivery mechanism, never the authorisation."""
    signed_in.force_login(accountant)
    quotation = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/quotations", data={"pdf": a_pdf()}
        )
    )

    client.force_login(with_role(constants.ROLE_STORE))
    response = client.get(f"/api/v1/quotations/{quotation['id']}/pdf")

    assert response.status_code == 403


@pytest.mark.django_db
def test_the_revision_chain_is_visible_on_the_card(client, accountant, card):
    client.force_login(accountant)
    first = body(
        client.post(
            f"/api/v1/job-cards/{card['id']}/quotations", data={"pdf": a_pdf()}
        )
    )

    second = body(
        client.post(
            f"/api/v1/job-cards/{card['id']}/quotations", data={"pdf": a_pdf("rev2.pdf")}
        )
    )

    assert second["revision_no"] == 1
    assert second["supersedes_id"] == first["id"]

    detail = body(client.get(f"/api/v1/job-cards/{card['id']}"))
    statuses = {q["revision_no"]: q["status"] for q in detail["quotations"]}
    assert statuses == {0: QuotationStatus.SUPERSEDED, 1: QuotationStatus.DRAFT}


# --- dashboard -----------------------------------------------------------------------


@pytest.mark.django_db
def test_recent_activity_drops_off_after_its_time_window(signed_in, card):
    from datetime import timedelta

    from django.utils import timezone

    from apps.pipeline.models import JobLineTransition

    category = ProductCategoryFactory(code="APIACTIVITYCAT")
    line = body(
        signed_in.post(
            f"/api/v1/job-cards/{card['id']}/lines",
            data=json.dumps(
                {"product_category_id": str(category.id), "description": "Panel"}
            ),
            content_type="application/json",
        )
    )
    signed_in.post(
        f"/api/v1/job-lines/{line['id']}/transitions",
        data=json.dumps({"action_code": "cancel", "note": "Stale test activity."}),
        content_type="application/json",
    )
    JobLineTransition.objects.update(performed_at=timezone.now() - timedelta(days=8))

    dashboard = body(signed_in.get("/api/v1/dashboard"))
    assert dashboard["recent_activity"] == []
