"""The pipeline engine.

``perform_transition`` is the only way a job line changes stage. It does not
assign ``current_stage_id`` — the ``apply_transition()`` trigger does that when
the transition row is inserted, under ``FOR UPDATE``. Python's job is to decide
whether the move is *allowed*; the database's job is to decide whether it is
still *valid* by the time it lands. Duplicating the second check in Python
would only widen the race window it is meant to close.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from django.db import DatabaseError, IntegrityError, transaction

from apps.core.db import audit_actor
from apps.core.exceptions import (
    ConfigurationError,
    PermissionDenied,
    RuleViolation,
    StaleTransition,
)
from apps.identity.selectors import active_role_ids_for
from apps.pipeline.conditions import evaluate
from apps.pipeline.models import JobLineTransition, TransitionRule

logger = logging.getLogger(__name__)


def condition_context(job_line, *, has_quotation_pdf: bool | None = None) -> dict[str, Any]:
    """The vocabulary a ``condition_expr`` may use.

    Flat scalars only, and deliberately finite. Rule authors get a documented
    set of names; the evaluator gets no route from a value back into a Python
    object. Extending this is a code change, which is the right friction for
    something that widens what an admin-authored expression can see.

    ``has_quotation_pdf`` backs the "negotiate" rule's gate (a card must
    actually have been quoted before its lines can move to Negotiation). A
    caller checking one line — ``perform_transition`` — leaves it unset and
    this looks it up with a single query; a caller checking a whole board
    (``apps.pipeline.selectors.available_actions_bulk``) precomputes it for
    every line in one query and passes the answer in, so this never becomes
    an N+1 across the board.
    """
    card = job_line.job_card
    category = job_line.product_category
    if has_quotation_pdf is None:
        from apps.sales.selectors import has_quotation_pdf_for_card

        has_quotation_pdf = has_quotation_pdf_for_card(job_line.job_card_id)
    return {
        "quantity": job_line.quantity,
        "line_status": job_line.line_status,
        "line_no": job_line.line_no,
        "is_manufactured": category.is_manufactured,
        "product_category": str(category.code),
        "dispatch_policy": card.dispatch_policy,
        "lifecycle_status": card.lifecycle_status,
        "enquiry_source": card.enquiry_source,
        "stage_code": str(job_line.current_stage.code),
        "sequence_no": job_line.current_stage.sequence_no,
        "has_quotation_pdf": has_quotation_pdf,
    }


def candidate_rules(user, job_line, action_code: str) -> list[TransitionRule]:
    """Active rules matching (current stage, action, one of the user's roles)."""
    return list(
        TransitionRule.objects.filter(
            from_stage_id=job_line.current_stage_id,
            action_code=action_code,
            allowed_role_id__in=active_role_ids_for(user),
            is_active=True,
        ).select_related("to_stage", "allowed_role")
    )


def _who_moved_it_here(job_line):
    """The actor on the line's most recent transition, or None.

    D4 chose reading (a): the person who moved the line into this stage may not
    move it out. That is answerable from ``pipeline_job_line_transitions``
    alone and needs no extra state.

    A line still at its initial stage has no transition row at all — creation
    deliberately writes none (see JobLineTransition's docstring) — so nobody
    "moved it here" and the gate does not apply.
    """
    latest = (
        JobLineTransition.objects.filter(job_line=job_line)
        .order_by("-performed_at", "-id")
        .values_list("performed_by", flat=True)
        .first()
    )
    return latest


def perform_transition(user, job_line, action_code: str, note: str | None = None):
    """Move ``job_line`` along ``action_code``. Returns the transition row.

    Where several rules match — a user holding two roles that both permit the
    action — the transition is allowed if *any* of them permits it. That
    mirrors how role grants union everywhere else in this system: holding an
    extra role never takes authority away. The rules must still agree on the
    destination, because two different destinations for one action is a
    configuration error nothing else catches.
    """
    # 1. Read the current stage. No row lock: apply_transition() takes
    #    FOR UPDATE at insert time and arbitrates.
    from_stage_id = job_line.current_stage_id

    # 2. Find the rules that could permit this.
    rules = candidate_rules(user, job_line, action_code)
    if not rules:
        raise PermissionDenied(
            f"You may not {action_code!r} this job line from its current stage.",
            action_code=action_code,
            stage=str(job_line.current_stage.code),
        )

    destinations = {rule.to_stage_id for rule in rules}
    if len(destinations) > 1:
        # UNIQUE (from_stage_id, action_code, allowed_role_id) permits two
        # roles to define the same action with different destinations. Nothing
        # in the schema catches it, and picking one arbitrarily would make the
        # pipeline non-deterministic for multi-role users.
        raise ConfigurationError(
            f"Transition rules disagree on where {action_code!r} leads from "
            f"{job_line.current_stage.code}. Fix the rules before continuing.",
            action_code=action_code,
            destinations=sorted(str(d) for d in destinations),
        )

    mover = _who_moved_it_here(job_line)
    context = condition_context(job_line)

    failures: list[Exception] = []
    permitting_rule: TransitionRule | None = None

    for rule in rules:
        try:
            _check_note(rule, note)
            _check_self_approval(rule, user, mover)
            _check_condition(rule, context)
        except ConfigurationError:
            # A broken expression is not something another role can excuse.
            raise
        except (PermissionDenied, RuleViolation) as exc:
            failures.append(exc)
            continue
        permitting_rule = rule
        break

    if permitting_rule is None:
        raise failures[0]

    # 6. Insert. The trigger validates staleness and advances the pointer.
    with audit_actor(user):
        try:
            # A savepoint: a stale transition aborts this statement, and
            # without one the surrounding transaction would be unusable.
            with transaction.atomic():
                _serialise_on(job_line)
                created = JobLineTransition.objects.create(
                    job_line=job_line,
                    from_stage_id=from_stage_id,
                    to_stage=permitting_rule.to_stage,
                    action_code=action_code,
                    performed_by=user,
                    note=(note or None),
                )
        except DatabaseError as exc:
            raise _translate(exc, job_line) from exc

    # The trigger moved current_stage_id in the database; the caller's object
    # still holds the old value. Without this refresh a second transition in
    # the same request would submit a from_stage the line has already left and
    # be rejected as stale — the caller's own write making their object wrong.
    job_line.refresh_from_db(fields=["current_stage"])
    return created


def _serialise_on(job_line) -> None:
    """Take the job line's row lock before inserting the transition.

    BACKEND_PLAN.md phase 4 step 1 says to take no row lock here, on the
    reasoning that ``apply_transition()`` already takes ``FOR UPDATE`` and
    duplicating it would only widen the window. That reasoning assumes the
    trigger's lock is the *first* lock each writer takes on the row. It is not.

    ``fk_job_line_transitions_line`` references ``sales_job_lines``, so
    inserting a transition takes a ``FOR KEY SHARE`` lock on the parent row.
    ``KEY SHARE`` is shared, so two concurrent writers both acquire it happily
    — and then the ``AFTER INSERT`` trigger asks each of them to upgrade to
    ``FOR UPDATE``, which neither can do while the other holds ``KEY SHARE``.
    PostgreSQL breaks the cycle by killing one with a deadlock, and the loser
    gets ``OperationalError: deadlock detected`` instead of a clean
    ``StaleTransition``. Measured: five deadlocks in six runs of the two-writer
    test before this line existed, zero after.

    Taking ``FOR UPDATE`` up front removes the upgrade: writers queue on an
    exclusive lock in a deterministic order. It does **not** duplicate the
    staleness check — ``from_stage_id`` is still whatever the caller believed
    before the lock, so the loser inserts a transition claiming a stage the
    line has left, and the trigger is still the sole arbiter that rejects it.
    """
    JobLine = job_line.__class__
    JobLine.objects.select_for_update().filter(pk=job_line.pk).values_list(
        "pk", flat=True
    ).first()


def _check_note(rule: TransitionRule, note: str | None) -> None:
    if rule.requires_note and not (note or "").strip():
        raise RuleViolation(
            f"A note is required to {rule.action_code} from {rule.from_stage_id}.",
            action_code=rule.action_code,
        )


def _check_self_approval(rule: TransitionRule, user, mover) -> None:
    """D4(a): whoever moved the line into this stage may not move it out."""
    if rule.allow_self_approval:
        return
    if mover is not None and str(mover) == str(user.pk):
        raise PermissionDenied(
            "This step needs a second person: you moved this line into its "
            "current stage, so you may not move it out.",
            action_code=rule.action_code,
        )


def _check_condition(rule: TransitionRule, context: dict[str, Any]) -> None:
    if not rule.condition_expr:
        return
    try:
        satisfied = evaluate(rule.condition_expr, context)
    except NotImplementedError as exc:
        # The prompt directs that an expression outside the allowlist raises
        # NotImplementedError. It reaches the caller as a configuration error
        # so it is noticed rather than mistaken for a permission problem.
        raise ConfigurationError(
            f"Transition rule {rule.pk} has an unsupported condition: {exc}",
            rule_id=str(rule.pk),
        ) from exc

    if not satisfied:
        raise RuleViolation(
            f"This job line does not meet the conditions for {rule.action_code!r}.",
            action_code=rule.action_code,
            condition=rule.condition_expr,
        )


def _translate(exc: Exception, job_line) -> Exception:
    """Turn the trigger's RAISE EXCEPTION into StaleTransition.

    ``apply_transition()`` raises a bare plpgsql exception, which psycopg
    surfaces as ``psycopg.errors.RaiseException`` (Django wraps it in
    ``InternalError``). Matching on the exception class rather than the message
    text keeps this working if the wording changes.
    """
    cause = exc.__cause__ or exc
    if isinstance(cause, psycopg.errors.RaiseException):
        return StaleTransition(
            "Someone else moved this job line first. Reload and try again.",
            job_line_id=str(job_line.pk),
        )
    if isinstance(exc, IntegrityError):
        return RuleViolation(f"That transition could not be recorded: {exc}")
    return exc
