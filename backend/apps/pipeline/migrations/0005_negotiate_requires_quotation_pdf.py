"""Gate ``negotiate`` (QUOTATION -> NEGOTIATION) on an actual quotation.

Until now the only checks on this transition were role and note — a line
could move straight to Negotiation with no quotation ever created for its
card, which makes no sense (there is nothing to negotiate). The evaluator
in ``apps.pipeline.conditions`` and the ``has_quotation_pdf`` name in
``apps.pipeline.services.condition_context`` already exist for exactly this
kind of rule; this migration is the data change that turns the gate on for
every role currently holding the edge (SALES/OWNER from 0003, ACCT from
0004).

Scoped by (from_stage, action_code) rather than by row id, so it reaches
whichever roles hold the edge at migrate time without hardcoding them here.
"""

from django.db import migrations

_FROM_STAGE = "QUOTATION"
_ACTION = "negotiate"
_CONDITION = "has_quotation_pdf"


def set_condition(apps, schema_editor):
    TransitionRule = apps.get_model("pipeline", "TransitionRule")
    TransitionRule.objects.filter(
        from_stage__code=_FROM_STAGE, action_code=_ACTION
    ).update(condition_expr=_CONDITION)


def clear_condition(apps, schema_editor):
    TransitionRule = apps.get_model("pipeline", "TransitionRule")
    TransitionRule.objects.filter(
        from_stage__code=_FROM_STAGE, action_code=_ACTION, condition_expr=_CONDITION
    ).update(condition_expr=None)


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0004_accounts_negotiate_permission"),
    ]

    operations = [
        migrations.RunPython(set_condition, clear_condition),
    ]
