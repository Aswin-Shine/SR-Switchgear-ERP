"""Seed the sales conveyor: six stages and eleven edges (D5, Appendix C).

``module_code = 'JOB'`` for every stage. One value, not one per department,
because a job line has a single ``current_stage_id`` that must travel from
enquiry through to dispatch. Other module codes are reserved for genuinely
separate pipelines — a purchase requisition, say.

``sequence_no`` is left with wide gaps (10, 20, 30, 40, then 900/910) so
design, purchase, production and dispatch can be inserted later without
renumbering anything.

Two consequences of this graph worth seeing:

* A quotation *revision* is not a transition. The line stays at QUOTATION and a
  new ``sales_quotations`` row supersedes the old one. ``ck_transition_rules_loop``
  forbids an edge from a stage to itself, which is consistent with that.
* ``cancel`` needs one rule per non-terminal stage per role, so a universal
  action multiplies rows. That is the cost of the model, not a defect — it is
  what makes adding a department an INSERT rather than a migration.

This migration depends on identity/0002 because every rule references a role.
"""

from django.db import migrations

from apps.identity.constants import ROLE_OWNER, ROLE_SALES

MODULE = "JOB"

STAGE_ENQUIRY = "ENQUIRY"
STAGE_QUOTATION = "QUOTATION"
STAGE_NEGOTIATION = "NEGOTIATION"
STAGE_ORDER_CONFIRMED = "ORDER_CONFIRMED"
STAGE_LOST = "LOST"
STAGE_CANCELLED = "CANCELLED"

# (code, name, sequence_no, is_initial, is_terminal)
STAGES = [
    (STAGE_ENQUIRY, "Enquiry", 10, True, False),
    (STAGE_QUOTATION, "Quotation", 20, False, False),
    (STAGE_NEGOTIATION, "Negotiation", 30, False, False),
    (STAGE_ORDER_CONFIRMED, "Order Confirmed", 40, False, False),
    (STAGE_LOST, "Lost", 900, False, True),
    (STAGE_CANCELLED, "Cancelled", 910, False, True),
]

# (from, action_code, to, [roles], requires_note, allow_self_approval)
#
# On the NEGOTIATION -> ORDER_CONFIRMED gate: Appendix C leaves self-approval
# "see D4", and D4 resolves to reading (a). It is seeded TRUE, matching the
# schema review's guidance that the design head and production manager are
# currently the same person — "set it TRUE today so work is not blocked; set it
# FALSE on the gate once a deputy exists. No schema change required, one
# UPDATE." The engine enforces FALSE correctly either way; this is the seed
# value, not the capability.
RULES = [
    (STAGE_ENQUIRY, "quote", STAGE_QUOTATION, [ROLE_SALES, ROLE_OWNER], False, True),
    (STAGE_ENQUIRY, "cancel", STAGE_CANCELLED, [ROLE_SALES, ROLE_OWNER], True, True),
    (STAGE_QUOTATION, "negotiate", STAGE_NEGOTIATION, [ROLE_SALES, ROLE_OWNER], False, True),
    (STAGE_QUOTATION, "rework", STAGE_ENQUIRY, [ROLE_SALES, ROLE_OWNER], True, True),
    (STAGE_QUOTATION, "lose", STAGE_LOST, [ROLE_SALES, ROLE_OWNER], True, True),
    (STAGE_QUOTATION, "cancel", STAGE_CANCELLED, [ROLE_SALES, ROLE_OWNER], True, True),
    (STAGE_NEGOTIATION, "confirm", STAGE_ORDER_CONFIRMED, [ROLE_OWNER], False, True),
    (STAGE_NEGOTIATION, "rework", STAGE_QUOTATION, [ROLE_SALES, ROLE_OWNER], True, True),
    (STAGE_NEGOTIATION, "lose", STAGE_LOST, [ROLE_SALES, ROLE_OWNER], True, True),
    (STAGE_NEGOTIATION, "cancel", STAGE_CANCELLED, [ROLE_SALES, ROLE_OWNER], True, True),
    (STAGE_ORDER_CONFIRMED, "cancel", STAGE_CANCELLED, [ROLE_OWNER], True, True),
]


def seed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    TransitionRule = apps.get_model("pipeline", "TransitionRule")
    Role = apps.get_model("identity", "Role")

    stages = {}
    for code, name, sequence_no, is_initial, is_terminal in STAGES:
        stage, _ = Stage.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module_code": MODULE,
                "sequence_no": sequence_no,
                "is_initial": is_initial,
                "is_terminal": is_terminal,
                "is_active": True,
            },
        )
        stages[code] = stage

    roles = {role.code: role for role in Role.objects.all()}

    for from_code, action, to_code, role_codes, requires_note, self_approval in RULES:
        for role_code in role_codes:
            role = roles.get(role_code)
            if role is None:  # pragma: no cover — identity/0002 seeds these
                raise RuntimeError(f"Role {role_code} is missing; run identity/0002 first.")
            TransitionRule.objects.update_or_create(
                from_stage=stages[from_code],
                action_code=action,
                allowed_role=role,
                defaults={
                    "to_stage": stages[to_code],
                    "requires_note": requires_note,
                    "allow_self_approval": self_approval,
                    "is_active": True,
                },
            )


def unseed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    TransitionRule = apps.get_model("pipeline", "TransitionRule")

    codes = [code for code, *_ in STAGES]
    TransitionRule.objects.filter(from_stage__code__in=codes).delete()
    # fk_job_lines_stage is ON DELETE RESTRICT, so a stage that any job line
    # still points at will refuse to be deleted. That is the correct outcome:
    # removing it would orphan live work.
    Stage.objects.filter(code__in=codes, job_lines__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0002_initial"),
        ("identity", "0002_roles_and_permission_grid"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
