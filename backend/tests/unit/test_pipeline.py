"""The pipeline engine: rules, gates, and the transition trigger."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.exceptions import (
    ConfigurationError,
    PermissionDenied,
    RuleViolation,
    StaleTransition,
)
from apps.identity import constants
from apps.identity.models import Role
from apps.pipeline.models import JobLineTransition, Stage, TransitionRule
from apps.pipeline.selectors import board_visible_lines
from apps.pipeline.services import perform_transition
from tests.factories import (
    DocumentFactory,
    JobCardFactory,
    JobLineFactory,
    ProductCategoryFactory,
    QuotationFactory,
    TransitionRuleFactory,
    UserAccountFactory,
    UserRoleFactory,
)


def with_role(code: str):
    user = UserAccountFactory()
    UserRoleFactory(user=user, role=Role.objects.get(code=code))
    return user


def with_quotation_pdf(card):
    """Attach a live quotation with a PDF to ``card`` — satisfies the
    "confirm" rule's ``has_quotation_pdf`` gate (pipeline migration 0006)."""
    QuotationFactory(job_card=card, pdf_document=DocumentFactory())


@pytest.fixture
def graph(db):
    """The seeded Appendix C conveyor."""
    return {stage.code: stage for stage in Stage.objects.filter(module_code="JOB")}


@pytest.fixture
def sales(db):
    return with_role(constants.ROLE_SALES)


@pytest.fixture
def owner(db):
    return with_role(constants.ROLE_OWNER)


@pytest.fixture
def line(db, graph, sales):
    """A job line sitting at the initial stage, on a card the salesperson owns."""
    return JobLineFactory(
        job_card=JobCardFactory(owner_user=sales),
        current_stage=graph["ENQUIRY"],
        product_category=ProductCategoryFactory(code="PANEL-LT"),
    )


# --- the seeded graph ------------------------------------------------------------


@pytest.mark.django_db
def test_the_appendix_c_graph_is_seeded(graph):
    """NEGOTIATION's row still exists — historical transition rows reference
    it and it is never deleted (pipeline migration 0006) — but it is
    deactivated, merged into QUOTATION."""
    assert set(graph) == {
        "ENQUIRY",
        "QUOTATION",
        "NEGOTIATION",
        "ORDER_CONFIRMED",
        "LOST",
        "CANCELLED",
    }
    assert graph["ENQUIRY"].is_initial is True
    assert graph["LOST"].is_terminal is True
    assert graph["CANCELLED"].is_terminal is True
    assert graph["NEGOTIATION"].is_active is False


@pytest.mark.django_db
def test_the_seven_edges_are_seeded_one_row_per_role(graph):
    """A rule open to two roles is two rows. Seven edges survive the
    NEGOTIATION merge (pipeline migration 0006): quote is open to
    SALES/OWNER/ACCT (three rows); cancel (from ENQUIRY, QUOTATION and
    ORDER_CONFIRMED), rework and lose are each open to SALES/OWNER (two rows
    apiece); confirm is OWNER-only (one row). Thirteen rows in all."""
    rules = TransitionRule.objects.filter(from_stage__module_code="JOB")
    edges = {(r.from_stage.code, r.action_code, r.to_stage.code) for r in rules}

    assert len(edges) == 7
    assert ("ENQUIRY", "quote", "QUOTATION") in edges
    assert ("QUOTATION", "confirm", "ORDER_CONFIRMED") in edges
    assert ("QUOTATION", "rework", "ENQUIRY") in edges
    assert not any(
        from_code == "NEGOTIATION" or to_code == "NEGOTIATION" for from_code, _, to_code in edges
    )
    assert rules.count() == 13


@pytest.mark.django_db
def test_only_the_owner_may_confirm_an_order(graph):
    confirming = TransitionRule.objects.filter(action_code="confirm")
    assert {r.allowed_role.code for r in confirming} == {constants.ROLE_OWNER}


# --- happy path -------------------------------------------------------------------


@pytest.mark.django_db
def test_a_permitted_transition_advances_the_line(sales, line, graph):
    transition = perform_transition(sales, line, "quote")

    line.refresh_from_db()
    assert line.current_stage_id == graph["QUOTATION"].id
    assert transition.from_stage_id == graph["ENQUIRY"].id
    assert transition.performed_by_id == sales.id


@pytest.mark.django_db
def test_the_pointer_is_moved_by_the_trigger_not_by_python(sales, line, graph):
    """perform_transition never assigns current_stage_id. If the trigger were
    dropped, this would fail — which is the point."""
    perform_transition(sales, line, "quote")

    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_stage_id FROM sales_job_lines WHERE id = %s", [str(line.id)]
        )
        assert str(cursor.fetchone()[0]) == str(graph["QUOTATION"].id)


@pytest.mark.django_db
def test_history_is_appended_not_replaced(sales, owner, line, graph):
    perform_transition(sales, line, "quote")
    with_quotation_pdf(line.job_card)
    perform_transition(owner, line, "confirm")

    history = list(
        JobLineTransition.objects.filter(job_line=line).order_by("id").values_list(
            "action_code", flat=True
        )
    )
    assert history == ["quote", "confirm"]


# --- confirm requires an actual quotation ----------------------------------------------


@pytest.mark.django_db
def test_confirm_is_refused_without_a_quotation_pdf(sales, owner, line, graph):
    """There is nothing to confirm on a card nobody has quoted yet."""
    perform_transition(sales, line, "quote")

    with pytest.raises(RuleViolation, match="does not meet the conditions"):
        perform_transition(owner, line, "confirm")

    line.refresh_from_db()
    assert line.current_stage_id == graph["QUOTATION"].id


@pytest.mark.django_db
def test_confirm_succeeds_once_a_quotation_pdf_exists(sales, owner, line, graph):
    perform_transition(sales, line, "quote")
    with_quotation_pdf(line.job_card)

    perform_transition(owner, line, "confirm")

    line.refresh_from_db()
    assert line.current_stage_id == graph["ORDER_CONFIRMED"].id


@pytest.mark.django_db
def test_confirm_is_refused_when_the_only_quotation_has_no_pdf(sales, owner, line, graph):
    """A draft revision created without a file does not count — the gate
    checks for an attached PDF specifically, not just a Quotation row."""
    perform_transition(sales, line, "quote")
    QuotationFactory(job_card=line.job_card)  # no pdf_document

    with pytest.raises(RuleViolation, match="does not meet the conditions"):
        perform_transition(owner, line, "confirm")


@pytest.mark.django_db
def test_rework_lose_cancel_do_not_require_a_quotation(sales, line, graph):
    """Only "confirm" is gated — reworking, losing, or cancelling an
    enquiry that was never quoted is a normal outcome, not a defect."""
    perform_transition(sales, line, "quote")

    perform_transition(sales, line, "rework", note="No response from client.")
    line.refresh_from_db()
    assert line.current_stage_id == graph["ENQUIRY"].id

    perform_transition(sales, line, "quote")
    perform_transition(sales, line, "lose", note="Client went with a competitor.")
    line.refresh_from_db()
    assert line.current_stage_id == graph["LOST"].id


# --- rule matching ------------------------------------------------------------------


@pytest.mark.django_db
def test_an_action_with_no_rule_for_the_users_roles_is_refused(sales, line):
    """Sales may not confirm an order — only the Owner may."""
    perform_transition(sales, line, "quote")
    with_quotation_pdf(line.job_card)

    with pytest.raises(PermissionDenied):
        perform_transition(sales, line, "confirm")


@pytest.mark.django_db
def test_an_unknown_action_is_refused(sales, line):
    with pytest.raises(PermissionDenied):
        perform_transition(sales, line, "teleport")


@pytest.mark.django_db
def test_an_action_valid_elsewhere_is_refused_from_the_wrong_stage(sales, line):
    """`confirm` exists, but not out of ENQUIRY."""
    with pytest.raises(PermissionDenied):
        perform_transition(sales, line, "confirm")


@pytest.mark.django_db
def test_an_inactive_rule_is_ignored(sales, line):
    TransitionRule.objects.filter(action_code="quote").update(is_active=False)

    with pytest.raises(PermissionDenied):
        perform_transition(sales, line, "quote")


@pytest.mark.django_db
def test_a_user_whose_role_is_deactivated_loses_the_action(sales, line):
    Role.objects.filter(code=constants.ROLE_SALES).update(is_active=False)

    with pytest.raises(PermissionDenied):
        perform_transition(sales, line, "quote")


@pytest.mark.django_db
def test_rules_disagreeing_on_the_destination_raise_configuration_error(line, graph):
    """UNIQUE (from_stage, action_code, allowed_role) permits two roles to send
    one action to two different stages. Nothing in the database catches it, so
    the engine must."""
    user = UserAccountFactory()
    for role_code, destination in (
        (constants.ROLE_SALES, graph["QUOTATION"]),
        (constants.ROLE_ACCT, graph["CANCELLED"]),
    ):
        role = Role.objects.get(code=role_code)
        UserRoleFactory(user=user, role=role)
        TransitionRule.objects.update_or_create(
            from_stage=graph["ENQUIRY"],
            action_code="ambiguous",
            allowed_role=role,
            defaults={"to_stage": destination, "is_active": True},
        )

    with pytest.raises(ConfigurationError, match="disagree"):
        perform_transition(user, line, "ambiguous")


@pytest.mark.django_db
def test_holding_a_second_role_never_removes_authority(line, graph):
    """Two roles permit the action and agree on the destination; one demands a
    note and the other does not. Role grants union everywhere else in this
    system, so the permissive rule wins."""
    user = UserAccountFactory()
    strict_role = Role.objects.get(code=constants.ROLE_ACCT)
    UserRoleFactory(user=user, role=Role.objects.get(code=constants.ROLE_SALES))
    UserRoleFactory(user=user, role=strict_role)

    TransitionRule.objects.update_or_create(
        from_stage=graph["ENQUIRY"],
        action_code="quote",
        allowed_role=strict_role,
        defaults={"to_stage": graph["QUOTATION"], "requires_note": True, "is_active": True},
    )

    # Sales' rule requires no note, so this succeeds without one.
    perform_transition(user, line, "quote")
    line.refresh_from_db()
    assert line.current_stage_id == graph["QUOTATION"].id


# --- requires_note ------------------------------------------------------------------


@pytest.mark.django_db
def test_requires_note_is_enforced(sales, line):
    with pytest.raises(RuleViolation, match="note is required"):
        perform_transition(sales, line, "cancel")


@pytest.mark.django_db
def test_a_blank_note_does_not_satisfy_requires_note(sales, line):
    with pytest.raises(RuleViolation, match="note is required"):
        perform_transition(sales, line, "cancel", note="   ")


@pytest.mark.django_db
def test_a_real_note_satisfies_it(sales, line, graph):
    perform_transition(sales, line, "cancel", note="Client withdrew the enquiry.")

    line.refresh_from_db()
    assert line.current_stage_id == graph["CANCELLED"].id


# --- allow_self_approval (D4) ----------------------------------------------------------


@pytest.mark.django_db
def test_self_approval_blocks_whoever_moved_the_line_in(sales, owner, line, graph):
    """D4(a): the person who moved the line into this stage may not move it
    out."""
    TransitionRule.objects.filter(action_code="confirm").update(
        allow_self_approval=False
    )
    UserRoleFactory(user=sales, role=Role.objects.get(code=constants.ROLE_OWNER))

    # `sales` moves the line into QUOTATION ...
    perform_transition(sales, line, "quote")
    with_quotation_pdf(line.job_card)

    # ... so `sales` may not move it out again.
    with pytest.raises(PermissionDenied, match="second person"):
        perform_transition(sales, line, "confirm")

    # But somebody else may.
    perform_transition(owner, line, "confirm")
    line.refresh_from_db()
    assert line.current_stage_id == graph["ORDER_CONFIRMED"].id


@pytest.mark.django_db
def test_self_approval_does_not_apply_at_the_initial_stage(sales, line, graph):
    """A line at its initial stage has no transition row — creation writes
    none — so nobody moved it there and the gate cannot bite."""
    TransitionRule.objects.filter(action_code="quote").update(allow_self_approval=False)

    perform_transition(sales, line, "quote")

    line.refresh_from_db()
    assert line.current_stage_id == graph["QUOTATION"].id


@pytest.mark.django_db
def test_self_approval_true_permits_the_same_person(owner, line, graph):
    perform_transition(owner, line, "quote")
    with_quotation_pdf(line.job_card)
    perform_transition(owner, line, "confirm")

    line.refresh_from_db()
    assert line.current_stage_id == graph["ORDER_CONFIRMED"].id


# --- backward edges ---------------------------------------------------------------------


@pytest.mark.django_db
def test_a_backward_transition_succeeds_and_keeps_both_edges(sales, line, graph):
    """Rework is just a rule pointing at a lower sequence_no. No special
    mechanism, and the history keeps both directions."""
    perform_transition(sales, line, "quote")
    perform_transition(sales, line, "rework", note="Specification changed.")

    line.refresh_from_db()
    assert line.current_stage_id == graph["ENQUIRY"].id

    edges = [
        (t.from_stage.code, t.to_stage.code)
        for t in JobLineTransition.objects.filter(job_line=line)
        .select_related("from_stage", "to_stage")
        .order_by("id")
    ]
    assert edges == [("ENQUIRY", "QUOTATION"), ("QUOTATION", "ENQUIRY")]


# --- staleness -------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_stale_from_stage_raises(sales, line, graph):
    """The line is advanced behind the caller's back; the in-memory object now
    claims a stage the line has left."""
    perform_transition(sales, line, "quote")

    stale = type(line).objects.get(pk=line.pk)
    stale.current_stage_id = graph["ENQUIRY"].id  # what the caller still believes

    with pytest.raises(StaleTransition):
        perform_transition(sales, stale, "quote")


@pytest.mark.django_db
def test_the_transaction_survives_a_stale_transition(sales, line, graph):
    """The savepoint matters: after a caught StaleTransition the connection
    must still be usable, or a retry would fail for the wrong reason."""
    perform_transition(sales, line, "quote")

    stale = type(line).objects.get(pk=line.pk)
    stale.current_stage_id = graph["ENQUIRY"].id
    with pytest.raises(StaleTransition):
        perform_transition(sales, stale, "quote")

    # The connection still works, and the real state is intact.
    line.refresh_from_db()
    assert line.current_stage_id == graph["QUOTATION"].id


# --- lines move independently -------------------------------------------------------------


@pytest.mark.django_db
def test_two_lines_on_one_card_move_independently(sales, graph):
    """Defect #1 in the schema review: a single enquiry for 3 ATS panels and 2
    AMF panels cannot move as one unit."""
    card = JobCardFactory(owner_user=sales)
    category = ProductCategoryFactory(code="PANEL-IND")
    first = JobLineFactory(job_card=card, line_no=1, current_stage=graph["ENQUIRY"],
                           product_category=category)
    second = JobLineFactory(job_card=card, line_no=2, current_stage=graph["ENQUIRY"],
                            product_category=category)

    perform_transition(sales, first, "quote")

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.current_stage_id == graph["QUOTATION"].id
    assert second.current_stage_id == graph["ENQUIRY"].id


# --- conditions -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_satisfied_condition_permits_the_transition(sales, line, graph):
    TransitionRule.objects.filter(
        action_code="quote", allowed_role__code=constants.ROLE_SALES
    ).update(condition_expr="quantity > 0 and is_manufactured")

    perform_transition(sales, line, "quote")

    line.refresh_from_db()
    assert line.current_stage_id == graph["QUOTATION"].id


@pytest.mark.django_db
def test_an_unsatisfied_condition_blocks_it(sales, line):
    TransitionRule.objects.filter(action_code="quote").update(
        condition_expr="quantity > 1000"
    )

    with pytest.raises(RuleViolation, match="does not meet the conditions"):
        perform_transition(sales, line, "quote")


@pytest.mark.django_db
def test_a_condition_using_something_outside_the_allowlist_is_a_configuration_error(
    sales, line
):
    TransitionRule.objects.filter(action_code="quote").update(
        condition_expr="__import__('os').system('true')"
    )

    with pytest.raises(ConfigurationError, match="unsupported condition"):
        perform_transition(sales, line, "quote")


@pytest.mark.django_db
def test_a_condition_naming_an_unknown_field_is_a_configuration_error(sales, line):
    TransitionRule.objects.filter(action_code="quote").update(
        condition_expr="salary > 100"
    )

    with pytest.raises(ConfigurationError):
        perform_transition(sales, line, "quote")


@pytest.mark.django_db
def test_traded_goods_can_take_a_different_edge(sales, graph):
    """Defect #2: a non-manufactured line should be able to skip design and
    production. Expressed as a condition on the rule, not as a code branch."""
    traded = ProductCategoryFactory(code="TRADED-GOODS", is_manufactured=False)
    line = JobLineFactory(
        job_card=JobCardFactory(owner_user=sales),
        current_stage=graph["ENQUIRY"],
        product_category=traded,
    )
    TransitionRule.objects.filter(
        action_code="quote", allowed_role__code=constants.ROLE_SALES
    ).update(condition_expr="is_manufactured")

    with pytest.raises(RuleViolation):
        perform_transition(sales, line, "quote")

    # A rule for traded goods, pointing somewhere else.
    TransitionRuleFactory(
        from_stage=graph["ENQUIRY"],
        to_stage=graph["ORDER_CONFIRMED"],
        action_code="quote_traded",
        allowed_role=Role.objects.get(code=constants.ROLE_SALES),
        condition_expr="not is_manufactured",
    )

    perform_transition(sales, line, "quote_traded")
    line.refresh_from_db()
    assert line.current_stage_id == graph["ORDER_CONFIRMED"].id


# --- board visibility (auto-hide) ------------------------------------------------------------


@pytest.mark.django_db
def test_a_freshly_cancelled_line_stays_on_the_board(sales, line, graph):
    perform_transition(sales, line, "cancel", note="Client withdrew.")
    line.refresh_from_db()

    assert board_visible_lines([line]) == [line]


@pytest.mark.django_db
def test_a_line_cancelled_over_3_hours_ago_is_hidden(sales, line, graph):
    perform_transition(sales, line, "cancel", note="Client withdrew.")
    line.refresh_from_db()
    JobLineTransition.objects.filter(job_line=line).update(
        performed_at=timezone.now() - timedelta(hours=4)
    )

    assert board_visible_lines([line]) == []


@pytest.mark.django_db
def test_a_stage_with_no_configured_window_is_never_hidden(line, graph):
    """ENQUIRY has no board_hide_after_hours seeded — age never matters."""
    assert graph["ENQUIRY"].board_hide_after_hours is None
    assert board_visible_lines([line]) == [line]


@pytest.mark.django_db
def test_only_the_stale_cancelled_line_is_hidden_others_stay(sales, graph):
    card = JobCardFactory(owner_user=sales)
    category = ProductCategoryFactory(code="BOARDVIS")
    stale_cancelled = JobLineFactory(
        job_card=card, line_no=1, current_stage=graph["ENQUIRY"], product_category=category
    )
    still_open = JobLineFactory(
        job_card=card, line_no=2, current_stage=graph["ENQUIRY"], product_category=category
    )
    perform_transition(sales, stale_cancelled, "cancel", note="Client withdrew.")
    stale_cancelled.refresh_from_db()
    JobLineTransition.objects.filter(job_line=stale_cancelled).update(
        performed_at=timezone.now() - timedelta(hours=4)
    )

    assert board_visible_lines([stale_cancelled, still_open]) == [still_open]
