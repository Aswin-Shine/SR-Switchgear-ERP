"""Contract tests for the board and the transition endpoint."""

import json
import threading
from datetime import timedelta

import pytest
from django.db import connections
from django.test import Client
from django.utils import timezone

from apps.identity import constants
from apps.identity.models import Role, UserRole
from apps.pipeline.models import JobLineTransition, Stage, TransitionRule
from apps.sales.models import JobLine
from tests.factories import (
    ClientFactory,
    DepartmentFactory,
    DesignationFactory,
    DocumentFactory,
    EmployeeFactory,
    JobCardFactory,
    JobLineFactory,
    ProductCategoryFactory,
    QuotationFactory,
    UserAccountFactory,
    UserRoleFactory,
)

PASSWORD = "a-perfectly-good-password"


def body(response):
    return json.loads(response.content)


@pytest.fixture
def sales(db):
    user = UserAccountFactory(password=PASSWORD)
    UserRoleFactory(user=user, role=Role.objects.get(code=constants.ROLE_SALES))
    return user


@pytest.fixture
def signed_in(client, sales):
    client.force_login(sales)
    return client


@pytest.fixture
def line(db, sales):
    return JobLineFactory(
        job_card=JobCardFactory(owner_user=sales),
        current_stage=Stage.objects.get(code="ENQUIRY"),
        product_category=ProductCategoryFactory(code="APICAT"),
    )


# --- the board ------------------------------------------------------------------


@pytest.mark.django_db
def test_board_payload_shape(signed_in, line):
    payload = body(signed_in.get("/api/v1/board"))

    assert set(payload) == {"module_code", "columns", "total_lines"}
    column = payload["columns"][0]
    assert set(column) == {"stage", "lines"}

    enquiry = next(c for c in payload["columns"] if c["stage"]["code"] == "ENQUIRY")
    assert set(enquiry["lines"][0]) == {
        "id",
        "line_no",
        "description",
        "quantity",
        "line_status",
        "required_by",
        "product_category",
        "job_card",
        "available_actions",
        "quotation",
    }


@pytest.mark.django_db
def test_board_columns_are_in_pipeline_order(signed_in, line):
    payload = body(signed_in.get("/api/v1/board"))
    sequences = [c["stage"]["sequence_no"] for c in payload["columns"]]
    assert sequences == sorted(sequences)


@pytest.mark.django_db
def test_a_line_appears_in_the_column_it_sits_at(signed_in, line):
    payload = body(signed_in.get("/api/v1/board"))

    enquiry = next(c for c in payload["columns"] if c["stage"]["code"] == "ENQUIRY")
    quotation = next(c for c in payload["columns"] if c["stage"]["code"] == "QUOTATION")

    assert str(line.id) in [row["id"] for row in enquiry["lines"]]
    assert str(line.id) not in [row["id"] for row in quotation["lines"]]


@pytest.mark.django_db
def test_a_lines_quotation_stage_is_its_cards_highest_revision(signed_in, sales, line):
    """A quotation is created against the whole job card, not specific lines
    — the real "New revision" upload flow never populates QuotationLine (see
    NewRevisionDialog.tsx). The board must report the card's highest
    revision regardless, not require a per-line link that never exists."""
    QuotationFactory(
        job_card=line.job_card,
        revision_no=1,
        status="superseded",
        prepared_by=sales,
        pdf_document=DocumentFactory(),
    )
    newer = QuotationFactory(
        job_card=line.job_card,
        revision_no=2,
        status="draft",
        prepared_by=sales,
        pdf_document=DocumentFactory(),
    )

    payload = body(signed_in.get("/api/v1/board"))
    enquiry = next(c for c in payload["columns"] if c["stage"]["code"] == "ENQUIRY")
    row = next(r for r in enquiry["lines"] if r["id"] == str(line.id))

    assert row["quotation"] == {
        "quotation_no": newer.quotation_no,
        "revision_no": 2,
        "status": "draft",
    }


@pytest.mark.django_db
def test_two_lines_on_the_same_card_share_its_quotation_stage(signed_in, sales, line):
    """The actual bug this guards against: a quotation is per-card, so a
    second line on the same card must show the same quotation info as the
    first — not None because no QuotationLine links it specifically."""
    other_line = JobLineFactory(
        job_card=line.job_card,
        line_no=line.line_no + 1,
        current_stage=Stage.objects.get(code="ENQUIRY"),
        product_category=line.product_category,
    )
    quotation = QuotationFactory(
        job_card=line.job_card,
        status="draft",
        prepared_by=sales,
        pdf_document=DocumentFactory(),
    )

    payload = body(signed_in.get("/api/v1/board"))
    enquiry = next(c for c in payload["columns"] if c["stage"]["code"] == "ENQUIRY")
    rows = {r["id"]: r["quotation"] for r in enquiry["lines"]}

    expected = {
        "quotation_no": quotation.quotation_no,
        "revision_no": 0,
        "status": "draft",
    }
    assert rows[str(line.id)] == expected
    assert rows[str(other_line.id)] == expected


@pytest.mark.django_db
def test_a_line_with_no_quotation_yet_has_none_on_the_board(signed_in, line):
    payload = body(signed_in.get("/api/v1/board"))
    enquiry = next(c for c in payload["columns"] if c["stage"]["code"] == "ENQUIRY")
    row = next(r for r in enquiry["lines"] if r["id"] == str(line.id))

    assert row["quotation"] is None


@pytest.mark.django_db
def test_sales_only_sees_their_own_lines_on_the_board(signed_in, line):
    """Prevents client poaching between reps (migration 0008): another rep's
    line — and their client's name — never reaches this actor's board."""
    others_line = JobLineFactory(
        job_card=JobCardFactory(owner_user=UserAccountFactory(), client=ClientFactory()),
        current_stage=Stage.objects.get(code="ENQUIRY"),
        product_category=ProductCategoryFactory(code="OTHERREPCAT"),
    )

    payload = body(signed_in.get("/api/v1/board"))
    all_line_ids = {row["id"] for column in payload["columns"] for row in column["lines"]}

    assert str(line.id) in all_line_ids
    assert str(others_line.id) not in all_line_ids

    response = signed_in.get(f"/api/v1/job-lines/{others_line.id}")
    assert response.status_code == 403


@pytest.mark.django_db
def test_a_role_without_quotation_view_sees_no_quotation_stage(client, sales, line):
    """Design/Production/Purchase/Store may see the board (job_line:view) but
    not quotation contents (quotation:view) — the field must stay hidden, not
    just empty by coincidence."""
    QuotationFactory(
        job_card=line.job_card,
        status="draft",
        prepared_by=sales,
        pdf_document=DocumentFactory(),
    )
    designer = UserAccountFactory(password=PASSWORD)
    UserRoleFactory(user=designer, role=Role.objects.get(code=constants.ROLE_DESIGN))
    client.force_login(designer)

    payload = body(client.get("/api/v1/board"))
    enquiry = next(c for c in payload["columns"] if c["stage"]["code"] == "ENQUIRY")
    row = next(r for r in enquiry["lines"] if r["id"] == str(line.id))

    assert row["quotation"] is None


@pytest.mark.django_db
def test_available_actions_are_attached_to_each_line(signed_in, line):
    payload = body(signed_in.get("/api/v1/board"))
    enquiry = next(c for c in payload["columns"] if c["stage"]["code"] == "ENQUIRY")
    row = next(r for r in enquiry["lines"] if r["id"] == str(line.id))

    actions = {a["action_code"]: a for a in row["available_actions"]}
    assert set(actions) == {"quote", "cancel"}
    assert set(actions["quote"]) == {
        "action_code",
        "to_stage",
        "requires_note",
        "available",
        "blocked_by",
    }
    assert actions["quote"]["available"] is True
    assert actions["cancel"]["requires_note"] is True


@pytest.mark.django_db
def test_a_role_without_rules_sees_no_actions(signed_in, client, line):
    """Accounts may view the board but may not move a line once it is at
    QUOTATION — ACCT holds "quote" (0006, so its own PDF uploads can advance
    a line out of ENQUIRY) but none of confirm/rework/lose/cancel from there."""
    signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "quote"}),
        content_type="application/json",
    )

    accountant = UserAccountFactory(password=PASSWORD)
    UserRoleFactory(user=accountant, role=Role.objects.get(code=constants.ROLE_ACCT))
    client.force_login(accountant)

    payload = body(client.get("/api/v1/board"))
    quotation = next(c for c in payload["columns"] if c["stage"]["code"] == "QUOTATION")
    row = next(r for r in quotation["lines"] if r["id"] == str(line.id))

    assert row["available_actions"] == []


@pytest.mark.django_db
def test_a_blocked_action_is_reported_not_hidden(signed_in, sales, line):
    """A greyed-out button that explains itself beats one that vanishes."""
    TransitionRule.objects.filter(action_code="quote").update(
        condition_expr="quantity > 1000"
    )

    payload = body(signed_in.get("/api/v1/board"))
    enquiry = next(c for c in payload["columns"] if c["stage"]["code"] == "ENQUIRY")
    row = next(r for r in enquiry["lines"] if r["id"] == str(line.id))
    quote = next(a for a in row["available_actions"] if a["action_code"] == "quote")

    assert quote["available"] is False
    assert quote["blocked_by"] == "condition"


@pytest.mark.django_db
def test_confirm_is_greyed_out_without_a_quotation_pdf(signed_in, client, line):
    """The real-world case this guards: a line reaches QUOTATION but nobody
    has uploaded a quotation yet — "Confirm" must not be a live button."""
    signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "quote"}),
        content_type="application/json",
    )

    # confirm is OWNER-only (0003), so the check has to run as Owner —
    # `client` is the same test client `signed_in` wraps; re-login swaps roles.
    owner = UserAccountFactory(password=PASSWORD)
    UserRoleFactory(user=owner, role=Role.objects.get(code=constants.ROLE_OWNER))
    client.force_login(owner)

    payload = body(client.get("/api/v1/board"))
    quotation = next(c for c in payload["columns"] if c["stage"]["code"] == "QUOTATION")
    row = next(r for r in quotation["lines"] if r["id"] == str(line.id))
    confirm = next(a for a in row["available_actions"] if a["action_code"] == "confirm")
    rework = next(a for a in row["available_actions"] if a["action_code"] == "rework")

    assert confirm["available"] is False
    assert confirm["blocked_by"] == "condition"
    # Only "confirm" is gated — rework/lose/cancel stay live either way.
    assert rework["available"] is True


@pytest.mark.django_db
def test_confirm_becomes_available_once_a_quotation_pdf_exists(signed_in, client, sales, line):
    signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "quote"}),
        content_type="application/json",
    )
    QuotationFactory(job_card=line.job_card, prepared_by=sales, pdf_document=DocumentFactory())

    owner = UserAccountFactory(password=PASSWORD)
    UserRoleFactory(user=owner, role=Role.objects.get(code=constants.ROLE_OWNER))
    client.force_login(owner)

    payload = body(client.get("/api/v1/board"))
    quotation = next(c for c in payload["columns"] if c["stage"]["code"] == "QUOTATION")
    row = next(r for r in quotation["lines"] if r["id"] == str(line.id))
    confirm = next(a for a in row["available_actions"] if a["action_code"] == "confirm")

    assert confirm["available"] is True
    assert confirm["blocked_by"] is None


@pytest.mark.django_db
def test_a_broken_condition_greys_the_button_instead_of_breaking_the_board(
    signed_in, line
):
    """One bad expression must not take the whole board down for everyone."""
    TransitionRule.objects.filter(action_code="quote").update(
        condition_expr="__import__('os')"
    )

    response = signed_in.get("/api/v1/board")

    assert response.status_code == 200
    enquiry = next(
        c for c in body(response)["columns"] if c["stage"]["code"] == "ENQUIRY"
    )
    row = next(r for r in enquiry["lines"] if r["id"] == str(line.id))
    quote = next(a for a in row["available_actions"] if a["action_code"] == "quote")
    assert quote["available"] is False


@pytest.mark.django_db
def test_soft_deleted_lines_are_not_on_the_board(signed_in, line):
    line.deleted_at = timezone.now()
    line.save(update_fields=["deleted_at"])

    payload = body(signed_in.get("/api/v1/board"))
    all_ids = [r["id"] for c in payload["columns"] for r in c["lines"]]
    assert str(line.id) not in all_ids


@pytest.mark.django_db
def test_a_line_cancelled_over_3_hours_ago_drops_off_the_board(signed_in, line):
    """Pipeline migration 0007: CANCELLED hides from the board after 3
    hours. Nothing is deleted — the line just stops showing up here."""
    signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "cancel", "note": "Client withdrew."}),
        content_type="application/json",
    )
    JobLineTransition.objects.filter(job_line=line).update(
        performed_at=timezone.now() - timedelta(hours=4)
    )

    payload = body(signed_in.get("/api/v1/board"))
    all_ids = [r["id"] for c in payload["columns"] for r in c["lines"]]
    assert str(line.id) not in all_ids
    assert payload["total_lines"] == 0


@pytest.mark.django_db
def test_a_recently_cancelled_line_still_shows_on_the_board(signed_in, line):
    signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "cancel", "note": "Client withdrew."}),
        content_type="application/json",
    )

    payload = body(signed_in.get("/api/v1/board"))
    cancelled = next(c for c in payload["columns"] if c["stage"]["code"] == "CANCELLED")
    assert str(line.id) in [r["id"] for r in cancelled["lines"]]


@pytest.mark.django_db
def test_the_board_does_not_issue_a_query_per_line(signed_in, sales, django_assert_max_num_queries):
    """The N+1 the bulk selector exists to prevent. Twelve lines must cost the
    same number of queries as one."""
    card = JobCardFactory(owner_user=sales)
    category = ProductCategoryFactory(code="NPLUSONE")
    enquiry = Stage.objects.get(code="ENQUIRY")
    for n in range(12):
        JobLineFactory(
            job_card=card, line_no=n + 1, current_stage=enquiry, product_category=category
        )

    with django_assert_max_num_queries(15):
        signed_in.get("/api/v1/board")


# --- job line detail --------------------------------------------------------------


@pytest.mark.django_db
def test_job_line_detail_shape(signed_in, line):
    payload = body(signed_in.get(f"/api/v1/job-lines/{line.id}"))

    assert {"id", "current_stage", "history", "specs", "available_actions"} <= set(payload)
    assert payload["history"] == []


@pytest.mark.django_db
def test_history_appears_after_a_transition(signed_in, line):
    signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "quote"}),
        content_type="application/json",
    )

    payload = body(signed_in.get(f"/api/v1/job-lines/{line.id}"))

    assert len(payload["history"]) == 1
    entry = payload["history"][0]
    assert set(entry) == {
        "id",
        "from_stage",
        "to_stage",
        "action_code",
        "performed_by",
        "performed_at",
        "note",
    }
    assert entry["from_stage"] == "ENQUIRY"
    assert entry["to_stage"] == "QUOTATION"


@pytest.mark.django_db
def test_an_unknown_job_line_is_404(signed_in):
    import uuid

    assert signed_in.get(f"/api/v1/job-lines/{uuid.uuid4()}").status_code == 404


# --- performing a transition ----------------------------------------------------------


@pytest.mark.django_db
def test_a_transition_returns_201_and_the_new_stage(signed_in, line):
    response = signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "quote"}),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = body(response)
    assert payload["to_stage"] == "QUOTATION"
    assert payload["current_stage"]["code"] == "QUOTATION"
    # confirm is OWNER-only (0003), so Sales does not see it here.
    assert {a["action_code"] for a in payload["available_actions"]} == {
        "rework",
        "lose",
        "cancel",
    }


@pytest.mark.django_db
def test_an_action_the_user_may_not_perform_is_403(signed_in, line):
    response = signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "confirm"}),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert body(response)["error"]["code"] == "permission_denied"


@pytest.mark.django_db
def test_a_missing_required_note_is_422(signed_in, line):
    response = signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "cancel"}),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert body(response)["error"]["code"] == "rule_violation"


@pytest.mark.django_db
def test_a_missing_action_code_is_422(signed_in, line):
    response = signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert body(response)["error"]["context"]["missing"] == ["action_code"]


@pytest.mark.django_db
def test_a_misconfigured_rule_surfaces_as_500_not_403(signed_in, line):
    """A ConfigurationError must not be mistaken for an ordinary permission
    problem — nothing the user does can fix it, so it has to be noticed."""
    TransitionRule.objects.filter(action_code="quote").update(
        condition_expr="__import__('os')"
    )

    response = signed_in.post(
        f"/api/v1/job-lines/{line.id}/transitions",
        data=json.dumps({"action_code": "quote"}),
        content_type="application/json",
    )

    assert response.status_code == 500
    assert body(response)["error"]["code"] == "configuration_error"


# --- the 409 race ---------------------------------------------------------------------


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("reference_data")
def test_two_requests_racing_the_same_transition_give_one_201_and_one_409():
    """The contract test the plan asks for, driven by two real connections.

    Whichever request loses must get 409 — a status the SPA can act on by
    reloading — rather than a 500 that would look like a server fault.
    """
    department = DepartmentFactory(code="APIRACEDEPT")
    designation = DesignationFactory(code="APIRACEDESIG")
    # OWNER, not SALES: this test races two connections against the same
    # transition to prove DB-level locking, not RBAC — SALES' job_line:view
    # is owner-scoped to one job card's owner_user, which only one of the two
    # racers could ever be. OWNER holds the same "quote" edge (0003) and is
    # unrestricted, so ownership of the card is irrelevant to either racer.
    owner_role = Role.objects.get(code=constants.ROLE_OWNER)

    users = []
    for index in range(2):
        employee = EmployeeFactory(
            employee_code=f"HR-APIRACE-{index}",
            department=department,
            designation=designation,
        )
        user = UserAccountFactory(username=f"apiracer{index}", employee=employee)
        UserRole.objects.create(user=user, role=owner_role)
        users.append(user)

    job_line = JobLineFactory(
        job_card=JobCardFactory(
            owner_user=users[0], client=ClientFactory(client_code="APIRACECLIENT")
        ),
        current_stage=Stage.objects.get(code="ENQUIRY"),
        product_category=ProductCategoryFactory(code="APIRACECAT"),
    )

    statuses: list = [None, None]
    barrier = threading.Barrier(2)

    def attempt(index: int):
        try:
            http = Client()
            http.force_login(users[index])
            barrier.wait(timeout=10)
            response = http.post(
                f"/api/v1/job-lines/{job_line.id}/transitions",
                data=json.dumps({"action_code": "quote"}),
                content_type="application/json",
            )
            statuses[index] = response.status_code
        except Exception as exc:
            statuses[index] = f"raised {type(exc).__name__}: {exc}"
        finally:
            connections.close_all()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(str(s) for s in statuses) == ["201", "409"], statuses

    # And exactly one transition was recorded.
    from apps.pipeline.models import JobLineTransition

    assert JobLineTransition.objects.filter(job_line=job_line).count() == 1
    assert JobLine.objects.get(pk=job_line.pk).current_stage.code == "QUOTATION"
