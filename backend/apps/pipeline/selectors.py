"""Reads for the pipeline app."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import QuerySet

from apps.pipeline.models import Stage, TransitionRule

#: The conveyor Module 2 runs on (Appendix C). One module code for the whole
#: sales-to-dispatch pipeline, because a job line has a single current_stage_id
#: that must travel from enquiry to dispatch. Other module codes are reserved
#: for genuinely separate pipelines.
JOB_MODULE = "JOB"


def stages_for_module(module_code: str = JOB_MODULE) -> QuerySet[Stage]:
    return (
        Stage.objects.filter(module_code=module_code, is_active=True)
        .select_related("department")
        .order_by("sequence_no")
    )


def initial_stage(module_code: str = JOB_MODULE) -> Stage | None:
    """The one active initial stage, guaranteed unique by uk_stages_one_initial."""
    return Stage.objects.filter(
        module_code=module_code, is_initial=True, is_active=True
    ).first()


def _serialise_action(rule: TransitionRule, *, blocked_by: str | None) -> dict:
    return {
        "action_code": rule.action_code,
        "to_stage": {
            "id": str(rule.to_stage_id),
            "code": str(rule.to_stage.code),
            "name": rule.to_stage.name,
        },
        "requires_note": rule.requires_note,
        "available": blocked_by is None,
        "blocked_by": blocked_by,
    }


def _block_reason(rule: TransitionRule, user, mover, context) -> str | None:
    """Why this action would be refused right now, or None if it would go through.

    Reported rather than hidden: a greyed-out button that explains itself
    ("needs a second person") is a usable interface; one that silently vanishes
    is not. The engine re-checks all of this at transition time regardless —
    this is advisory, and never the thing that enforces the rule.
    """
    from apps.pipeline.conditions import evaluate

    if not rule.allow_self_approval and mover is not None and str(mover) == str(user.pk):
        return "self_approval"

    if rule.condition_expr:
        try:
            if not evaluate(rule.condition_expr, context):
                return "condition"
        except Exception:
            # A broken expression must not take the whole board down. The
            # transition endpoint surfaces it as a ConfigurationError if
            # anyone actually tries the action; here it just greys the button.
            return "condition"

    return None


def available_actions(user, job_line) -> list[dict]:
    """What ``user`` may do to ``job_line`` from where it stands.

    One indexed query against ``idx_transition_rules_from``, filtered by the
    user's active roles. Use ``available_actions_bulk`` for a list of lines —
    calling this in a loop is an N+1 over the whole board.
    """
    return available_actions_bulk(user, [job_line])[job_line.pk]


def available_actions_bulk(user, job_lines) -> dict:
    """``{job_line_pk: [action, ...]}`` in a constant number of queries.

    Four queries total, whatever the size of the board: the rules for every
    stage in play, the last mover for every line, the user's roles, and which
    cards already have a quotation PDF (for the "negotiate" gate). The
    dashboard renders hundreds of lines, so this is the difference between one
    round trip and several hundred.
    """
    from apps.identity.selectors import active_role_ids_for
    from apps.pipeline.services import condition_context
    from apps.sales.selectors import quotation_pdf_exists_by_card

    job_lines = list(job_lines)
    if not job_lines:
        return {}

    role_ids = active_role_ids_for(user)
    if not role_ids:
        return {line.pk: [] for line in job_lines}

    stage_ids = {line.current_stage_id for line in job_lines}
    rules = (
        TransitionRule.objects.filter(
            from_stage_id__in=stage_ids,
            allowed_role_id__in=role_ids,
            is_active=True,
        )
        .select_related("to_stage")
        .order_by("to_stage__sequence_no", "action_code")
    )

    rules_by_stage: dict = {}
    for rule in rules:
        rules_by_stage.setdefault(rule.from_stage_id, []).append(rule)

    movers = _last_movers({line.pk for line in job_lines})
    quotation_pdfs = quotation_pdf_exists_by_card({line.job_card_id for line in job_lines})

    result: dict = {}
    for line in job_lines:
        candidates = rules_by_stage.get(line.current_stage_id, [])
        if not candidates:
            result[line.pk] = []
            continue

        context = condition_context(
            line, has_quotation_pdf=quotation_pdfs.get(line.job_card_id, False)
        )
        mover = movers.get(line.pk)

        # Several roles may offer the same action. Keep the most permissive
        # outcome, matching how perform_transition resolves them.
        best: dict[str, dict] = {}
        for rule in candidates:
            entry = _serialise_action(
                rule, blocked_by=_block_reason(rule, user, mover, context)
            )
            existing = best.get(rule.action_code)
            if existing is None or (entry["available"] and not existing["available"]):
                best[rule.action_code] = entry
        result[line.pk] = list(best.values())

    return result


def _last_movers(job_line_ids: set) -> dict:
    """``{job_line_pk: performed_by}`` for the latest transition on each line.

    DISTINCT ON is the one query that answers this without a window function
    or a correlated subquery, and it rides ``idx_job_line_transitions_line``
    (job_line_id, performed_at DESC) exactly.
    """
    if not job_line_ids:
        return {}

    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (job_line_id) job_line_id, performed_by
            FROM pipeline_job_line_transitions
            WHERE job_line_id = ANY(%s)
            ORDER BY job_line_id, performed_at DESC, id DESC
            """,
            [[str(pk) for pk in job_line_ids]],
        )
        return {row[0]: row[1] for row in cursor.fetchall()}


def board_visible_lines(lines: list) -> list:
    """Drop lines whose stage is configured to disappear from the board
    after some time (``Stage.board_hide_after_hours``) — e.g. a cancelled
    line stops appearing 3 hours after cancellation (pipeline migration
    0007). Nothing is deleted: the line, its card, and its full transition
    history are untouched — this only changes what ``GET /api/v1/board``
    groups and returns.
    """
    from django.utils import timezone

    hide_after = {
        line.current_stage_id: line.current_stage.board_hide_after_hours
        for line in lines
        if line.current_stage.board_hide_after_hours is not None
    }
    if not hide_after:
        return lines

    entered_at = _last_transition_at(
        {line.pk for line in lines if line.current_stage_id in hide_after}
    )
    now = timezone.now()
    visible = []
    for line in lines:
        hours = hide_after.get(line.current_stage_id)
        if hours is None:
            visible.append(line)
            continue
        since = entered_at.get(line.pk)
        # Fail open on a missing transition row rather than hide silently —
        # matches this file's existing philosophy (_block_reason reports
        # rather than hides).
        if since is None or now - since < timedelta(hours=hours):
            visible.append(line)
    return visible


def _last_transition_at(job_line_ids: set) -> dict:
    """``{job_line_pk: performed_at}`` for the latest transition on each
    line — same DISTINCT ON shape as ``_last_movers``, over
    ``idx_job_line_transitions_line``.
    """
    if not job_line_ids:
        return {}

    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (job_line_id) job_line_id, performed_at
            FROM pipeline_job_line_transitions
            WHERE job_line_id = ANY(%s)
            ORDER BY job_line_id, performed_at DESC, id DESC
            """,
            [[str(pk) for pk in job_line_ids]],
        )
        return {row[0]: row[1] for row in cursor.fetchall()}


def transition_history(job_line) -> list:
    from apps.pipeline.models import JobLineTransition

    return list(
        JobLineTransition.objects.filter(job_line=job_line)
        .select_related("from_stage", "to_stage", "performed_by")
        .order_by("-performed_at", "-id")
    )
