"""Admin for the stage graph.

This is the screen that makes "adding a department is an INSERT, not a
migration" true in practice. It is also, for the same reason, the most
dangerous screen in the system: ``condition_expr`` is evaluated at transition
time, and ``allow_self_approval`` is what enforces a two-person rule. The
schema review says to restrict write access here to a single administrative
role, and the grid does exactly that — only OWNER and ADMIN hold
``transition_rule:edit``.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import RBACModelAdmin, ReadOnlyAdmin
from apps.identity import constants
from apps.pipeline.models import JobLineTransition, Stage, TransitionRule


@admin.register(Stage)
class StageAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_TRANSITION_RULE
    list_display = ("module_code", "sequence_no", "code", "name", "department",
                    "is_initial", "is_terminal", "is_active", "board_hide_after_hours",
                    "cascades_job_card_status")
    list_filter = ("module_code", "is_active", "is_initial", "is_terminal")
    search_fields = ("code", "name")
    ordering = ("module_code", "sequence_no")
    autocomplete_fields = ("department",)


@admin.register(TransitionRule)
class TransitionRuleAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_TRANSITION_RULE
    list_display = ("from_stage", "action_code", "to_stage", "allowed_role",
                    "requires_note", "allow_self_approval", "is_active")
    list_filter = ("is_active", "requires_note", "allow_self_approval", "allowed_role")
    search_fields = ("action_code", "from_stage__code", "to_stage__code")
    ordering = ("from_stage__sequence_no", "action_code")
    autocomplete_fields = ("from_stage", "to_stage", "allowed_role")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("from_stage", "to_stage", "allowed_role")
        )


@admin.register(JobLineTransition)
class JobLineTransitionAdmin(ReadOnlyAdmin):
    """Append-only history. Editing a transition would desynchronise it from
    ``job_lines.current_stage_id``, which is the one thing
    ``apply_transition()`` exists to prevent."""

    rbac_resource = constants.RES_JOB_LINE
    list_display = ("job_line", "from_stage", "to_stage", "action_code",
                    "performed_by", "performed_at")
    list_filter = ("action_code", "to_stage")
    search_fields = ("job_line__id", "performed_by__username")
    date_hierarchy = "performed_at"
    ordering = ("-performed_at",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("job_line", "from_stage", "to_stage", "performed_by")
        )


StageAdmin.search_fields = ("code", "name")
