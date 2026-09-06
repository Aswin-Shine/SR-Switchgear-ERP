"""Grant ACCT the ``negotiate`` transition (QUOTATION -> NEGOTIATION).

apps/sales/services.py::create_quotation_revision auto-advances a job line
from QUOTATION to NEGOTIATION when a quotation PDF is attached, by calling
the same perform_transition() every manual "negotiate" click goes through
(0002_initial's engine, no bypass). That only succeeds for an actor whose
role holds a matching TransitionRule (0003_sales_stage_graph seeded
SALES/OWNER) — ACCT needs the identical row, or its own PDF uploads would
silently fail to advance the line while Sales's/Owner's did.

Same seed/unseed shape as 0003, scoped to exactly this one
(from_stage, action_code, role) triple.
"""

from django.db import migrations

from apps.identity.constants import ROLE_ACCT

_FROM_STAGE = "QUOTATION"
_ACTION = "negotiate"
_TO_STAGE = "NEGOTIATION"


def seed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    TransitionRule = apps.get_model("pipeline", "TransitionRule")
    Role = apps.get_model("identity", "Role")

    TransitionRule.objects.update_or_create(
        from_stage=Stage.objects.get(code=_FROM_STAGE),
        action_code=_ACTION,
        allowed_role=Role.objects.get(code=ROLE_ACCT),
        defaults={
            "to_stage": Stage.objects.get(code=_TO_STAGE),
            "requires_note": False,
            "allow_self_approval": True,
            "is_active": True,
        },
    )


def unseed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    TransitionRule = apps.get_model("pipeline", "TransitionRule")
    Role = apps.get_model("identity", "Role")

    TransitionRule.objects.filter(
        from_stage=Stage.objects.get(code=_FROM_STAGE),
        action_code=_ACTION,
        allowed_role=Role.objects.get(code=ROLE_ACCT),
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0003_sales_stage_graph"),
        ("identity", "0005_accounts_quotation_create_permission"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
