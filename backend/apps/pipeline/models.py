"""pipeline — the stage graph, shared by Module 2 and every future module.

Tables: pipeline_stages, pipeline_transition_rules, pipeline_job_line_transitions.

The architectural property worth protecting: adding a department to the
pipeline is an INSERT, never a schema migration. That is why stages are rows
and not an enum, and why no stage code appears as a literal anywhere in
application logic.
"""

from __future__ import annotations

from django.db import models

from apps.core.fields import CITextField, Now, uuid_pk_kwargs
from apps.core.models import TimeStamped, fk


class Stage(TimeStamped):
    id = models.UUIDField(**uuid_pk_kwargs())
    code = CITextField()
    name = models.TextField()
    module_code = models.TextField(
        help_text="One conveyor per module. Appendix C uses 'JOB' for the whole "
                  "sales-to-dispatch pipeline.",
    )
    sequence_no = models.IntegerField(
        help_text="Linear order, with wide gaps so departments can be inserted "
                  "later without renumbering.",
    )
    department = fk(
        "core.Department", models.PROTECT, null=True, blank=True, related_name="stages"
    )
    is_initial = models.BooleanField(db_default=False, default=False)
    is_terminal = models.BooleanField(db_default=False, default=False)
    is_active = models.BooleanField(db_default=True, default=True)
    board_hide_after_hours = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Hours after a line enters this stage before it stops "
                  "appearing on GET /api/v1/board. NULL means never hidden. "
                  "Nothing is deleted — this only affects the board query.",
    )
    cascades_job_card_status = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="When every active line on a card reaches a stage sharing "
                  "this value, the card's own lifecycle_status is set to "
                  "match (see apps.sales.signals). A plain string mirroring "
                  "apps.sales.models.JobLifecycleStatus's values without "
                  "importing it — pipeline stays ignorant of sales. NULL "
                  "means this stage carries no card-level outcome.",
    )

    class Meta:
        db_table = "pipeline_stages"
        default_permissions = ()
        verbose_name = "stage"
        ordering = ["module_code", "sequence_no"]
        constraints = [
            # Note: globally unique, not per module. Two modules may not reuse
            # a stage code.
            models.UniqueConstraint(fields=["code"], name="uk_stages_code"),
            models.UniqueConstraint(
                fields=["module_code", "sequence_no"], name="uk_stages_sequence"
            ),
            models.CheckConstraint(
                condition=models.Q(sequence_no__gt=0), name="ck_stages_sequence"
            ),
            models.CheckConstraint(
                condition=~(models.Q(is_initial=True) & models.Q(is_terminal=True)),
                name="ck_stages_endpoints",
            ),
            models.CheckConstraint(
                condition=models.Q(cascades_job_card_status__isnull=True)
                | models.Q(cascades_job_card_status__in=["won", "lost", "cancelled"]),
                name="ck_stages_cascade_status",
            ),
            # Exactly one *active* initial stage per module. Deactivating the
            # old one is how you replace it.
            models.UniqueConstraint(
                fields=["module_code"],
                condition=models.Q(is_initial=True) & models.Q(is_active=True),
                name="uk_stages_one_initial",
            ),
        ]
        indexes = [
            models.Index(fields=["department"], name="idx_stages_department"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class TransitionRule(TimeStamped):
    """The allowed edges of the stage graph, with authority attached.

    A backward edge (rework, rejection) is simply a rule whose ``to_stage`` has
    a lower ``sequence_no``. There is no special mechanism, and none is needed.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    from_stage = fk("pipeline.Stage", models.PROTECT, related_name="outgoing_rules")
    action_code = models.TextField()
    to_stage = fk("pipeline.Stage", models.PROTECT, related_name="incoming_rules")
    allowed_role = fk("identity.Role", models.PROTECT, related_name="transition_rules")
    allow_self_approval = models.BooleanField(
        db_default=True,
        default=True,
        help_text="FALSE enforces the two-person rule: whoever moved the line "
                  "into this stage may not move it out (D4).",
    )
    requires_note = models.BooleanField(db_default=False, default=False)
    condition_expr = models.TextField(
        null=True,
        blank=True,
        help_text="Evaluated by a sandboxed allowlist parser at transition time. "
                  "Never eval(). Restrict write access to this column.",
    )
    is_active = models.BooleanField(db_default=True, default=True)

    class Meta:
        db_table = "pipeline_transition_rules"
        default_permissions = ()
        verbose_name = "transition rule"
        constraints = [
            # One row per (from_stage, action, role): a rule open to two roles
            # is two rows. Note what this does NOT prevent — two rows agreeing
            # on from_stage and action but disagreeing on to_stage across
            # different roles. Nothing in the database catches that, so
            # perform_transition() raises ConfigurationError for it.
            models.UniqueConstraint(
                fields=["from_stage", "action_code", "allowed_role"],
                name="uk_transition_rules",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_stage=models.F("to_stage")),
                name="ck_transition_rules_loop",
            ),
        ]
        indexes = [
            models.Index(fields=["from_stage"], name="idx_transition_rules_from"),
            models.Index(fields=["to_stage"], name="idx_transition_rules_to"),
            models.Index(fields=["allowed_role"], name="idx_transition_rules_role"),
        ]

    def __str__(self) -> str:
        return f"{self.from_stage_id} --{self.action_code}--> {self.to_stage_id}"


class JobLineTransition(models.Model):
    """Append-only stage history — the source of truth.

    ``sales_job_lines.current_stage_id`` is a denormalised cache of the latest
    row here, kept honest by the ``apply_transition()`` trigger that fires on
    insert.

    On ``from_stage`` being nullable: it reads as an invitation to log a line's
    entry into the initial stage with ``from_stage = NULL``. It cannot be used
    that way. ``job_lines.current_stage_id`` is NOT NULL, so a newly created
    line already sits at the initial stage, and ``apply_transition()`` raises
    *Stale transition* for any insert whose ``from_stage_id`` does not equal
    the line's current stage — including NULL. So job line creation writes no
    transition row at all; entry into the initial stage is recorded by
    ``job_lines.created_at`` and ``current_stage_id``. The column stays
    nullable and unused. (BACKEND_PLAN.md section 3, "One conflict in the
    schema itself".)
    """

    id = models.BigAutoField(primary_key=True)
    job_line = fk("sales.JobLine", models.CASCADE, related_name="transitions")
    from_stage = fk(
        "pipeline.Stage", models.PROTECT, null=True, blank=True,
        related_name="transitions_from",
    )
    to_stage = fk("pipeline.Stage", models.PROTECT, related_name="transitions_to")
    action_code = models.TextField()
    performed_by = fk(
        "identity.UserAccount", models.PROTECT,
        db_column="performed_by", related_name="transitions_performed",
    )
    performed_at = models.DateTimeField(db_default=Now(), editable=False)
    note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "pipeline_job_line_transitions"
        default_permissions = ()
        verbose_name = "job line transition"
        ordering = ["-performed_at", "-id"]
        indexes = [
            models.Index(
                fields=["job_line", "-performed_at"], name="idx_job_line_transitions_line"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.job_line_id}: {self.action_code} -> {self.to_stage_id}"
