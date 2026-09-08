"""Pipeline endpoints: the board, a job line, and moving one along."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404

from apps.core.api import api, iso, json_body, ok, require
from apps.identity import constants
from apps.identity.services import has_permission, owner_scope_for, require_permission
from apps.pipeline.models import Stage
from apps.pipeline.selectors import (
    JOB_MODULE,
    available_actions,
    available_actions_bulk,
    board_visible_lines,
    last_transition_at,
    stages_for_module,
    transition_history,
)
from apps.pipeline.services import perform_transition
from apps.sales.models import JobLine
from apps.sales.selectors import latest_quotation_by_card


def serialize_stage(stage: Stage) -> dict:
    return {
        "id": str(stage.id),
        "code": str(stage.code),
        "name": stage.name,
        "module_code": stage.module_code,
        "sequence_no": stage.sequence_no,
        "department": stage.department.name if stage.department_id else None,
        "is_initial": stage.is_initial,
        "is_terminal": stage.is_terminal,
    }


def serialize_board_line(
    line: JobLine,
    actions: list[dict],
    quotation: dict | None = None,
    stage_entered_at=None,
) -> dict:
    return {
        "id": str(line.id),
        "line_no": line.line_no,
        "description": line.description,
        "quantity": line.quantity,
        "line_status": line.line_status,
        "required_by": iso(line.required_by),
        # When the line's current stage was entered — its most recent transition's
        # performed_at. None on job_line_detail (not passed there): that page already
        # shows the full transition history, so a redundant "time in stage" stat isn't
        # needed the way it is on the dense board.
        "stage_entered_at": iso(stage_entered_at) if stage_entered_at else None,
        "product_category": {
            "code": str(line.product_category.code),
            "name": line.product_category.name,
            "is_manufactured": line.product_category.is_manufactured,
        },
        "job_card": {
            "id": str(line.job_card_id),
            "job_no": line.job_card.job_no,
            "client": line.job_card.client.legal_name,
            "dispatch_policy": line.job_card.dispatch_policy,
        },
        "available_actions": actions,
        # The job card's current (highest-revision) quotation — a quotation
        # is created against the whole card, not specific lines (see
        # apps.sales.selectors.latest_quotation_by_card), so every line on
        # the same card shares this. None both when no quotation exists yet
        # and when the caller lacks quotation:view: the board is open to
        # roles (Design, Production, Purchase, Store...) that job_line:view
        # covers but quotation:view does not.
        "quotation": quotation,
    }


@api(["GET"])
def stages(request: HttpRequest) -> JsonResponse:
    """The board's columns, in order.

    Not paginated: a pipeline with enough stages to need paging is a pipeline
    nobody can read, and the SPA needs all of them to lay out the board.
    """
    module_code = request.GET.get("module_code", JOB_MODULE)
    return ok(
        {
            "module_code": module_code,
            "items": [serialize_stage(stage) for stage in stages_for_module(module_code)],
        }
    )


@api(["GET"])
def board(request: HttpRequest) -> JsonResponse:
    """Every open job line, grouped by the stage it sits at.

    The whole board in a constant number of queries: one for the stages, one
    for the lines, three inside ``available_actions_bulk``, and one more for
    ``last_transition_at`` (the board's per-line "time in stage" stat).
    Computing any of this per line would be an N+1 across the entire
    factory's work.

    A line whose stage has ``board_hide_after_hours`` set (CANCELLED, 3
    hours as of pipeline migration 0007) drops out of the result once that
    many hours have passed since its last transition — see
    ``board_visible_lines``. Nothing is deleted by this; the line, its card
    and its history are all still reachable elsewhere.
    """
    scope = owner_scope_for(request.user, constants.RES_JOB_LINE, "view")

    module_code = request.GET.get("module_code", JOB_MODULE)
    columns = list(stages_for_module(module_code))

    lines_qs = (
        JobLine.objects.filter(
            deleted_at__isnull=True,
            current_stage__module_code=module_code,
            job_card__deleted_at__isnull=True,
        )
        .select_related("job_card", "job_card__client", "product_category", "current_stage")
        .order_by("job_card__job_no", "line_no")
    )

    if scope is not None:
        # Owner-scoped (e.g. Sales): always their own cards, ignoring
        # whatever owner_user_id the client passed — an unrestricted viewer
        # opting into "just this person's lines" is a convenience filter, not
        # a security boundary, so only the unrestricted branch honours it.
        lines_qs = lines_qs.filter(job_card__owner_user=scope)
    elif owner_id := request.GET.get("owner_user_id"):
        lines_qs = lines_qs.filter(job_card__owner_user_id=owner_id)

    lines = board_visible_lines(list(lines_qs))

    actions = available_actions_bulk(request.user, lines)
    entered_at = last_transition_at({line.pk for line in lines})

    quotations: dict = {}
    if has_permission(request.user, constants.RES_QUOTATION, "view"):
        quotations = latest_quotation_by_card({line.job_card_id for line in lines})

    by_stage: dict = {stage.id: [] for stage in columns}
    for line in lines:
        by_stage.setdefault(line.current_stage_id, []).append(
            serialize_board_line(
                line,
                actions.get(line.pk, []),
                quotations.get(line.job_card_id),
                entered_at.get(line.pk),
            )
        )

    return ok(
        {
            "module_code": module_code,
            "columns": [
                {"stage": serialize_stage(stage), "lines": by_stage.get(stage.id, [])}
                for stage in columns
            ],
            "total_lines": len(lines),
        }
    )


@api(["GET"])
def job_line_detail(request: HttpRequest, line_id) -> JsonResponse:
    line = get_object_or_404(
        JobLine.objects.select_related(
            "job_card", "job_card__client", "product_category", "current_stage"
        ),
        pk=line_id,
        deleted_at__isnull=True,
    )
    require_permission(request.user, constants.RES_JOB_LINE, "view", obj=line)

    quotation = None
    if has_permission(request.user, constants.RES_QUOTATION, "view"):
        quotation = latest_quotation_by_card([line.job_card_id]).get(line.job_card_id)

    payload = serialize_board_line(line, available_actions(request.user, line), quotation)
    payload["current_stage"] = serialize_stage(line.current_stage)
    payload["specs"] = line.specs
    payload["history"] = [
        {
            "id": transition.id,
            "from_stage": str(transition.from_stage.code) if transition.from_stage_id else None,
            "to_stage": str(transition.to_stage.code),
            "action_code": transition.action_code,
            "performed_by": transition.performed_by.username,
            "performed_at": iso(transition.performed_at),
            "note": transition.note,
        }
        for transition in transition_history(line)
    ]
    return ok(payload)


@api(["POST"])
def create_transition(request: HttpRequest, line_id) -> JsonResponse:
    """Move a job line along.

    Every refusal has its own status code, mapped centrally by
    ``DomainErrorMiddleware``: 403 when no rule permits it or a two-person gate
    blocks it, 422 when a note is missing or a condition fails, and 409 when
    somebody else moved the line first. That last one is the case the SPA must
    handle by reloading rather than retrying.
    """
    line = get_object_or_404(
        JobLine.objects.select_related("job_card", "product_category", "current_stage"),
        pk=line_id,
        deleted_at__isnull=True,
    )
    require_permission(request.user, constants.RES_JOB_LINE, "view", obj=line)

    payload = json_body(request)
    (action_code,) = require(payload, "action_code")
    note = payload.get("note")

    transition = perform_transition(request.user, line, action_code, note=note)
    line.refresh_from_db()

    return ok(
        {
            "id": transition.id,
            "job_line_id": str(line.id),
            "from_stage": str(transition.from_stage.code) if transition.from_stage_id else None,
            "to_stage": str(transition.to_stage.code),
            "action_code": transition.action_code,
            "performed_at": iso(transition.performed_at),
            "note": transition.note,
            "current_stage": serialize_stage(line.current_stage),
            "available_actions": available_actions(request.user, line),
        },
        status=201,
    )
