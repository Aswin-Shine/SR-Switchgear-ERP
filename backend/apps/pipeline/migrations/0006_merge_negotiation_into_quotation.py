"""Merge NEGOTIATION into QUOTATION — one board column, not two.

Quotation and Negotiation were the same real-world step ("negotiating the
price on the quote we sent"), so this collapses them:

* Every job line still at NEGOTIATION is reclassified onto QUOTATION. This is
  an administrative reclassification, not a business transition — like a
  quotation revision (0003's docstring), it writes no
  ``pipeline_job_line_transitions`` row.
* The ``confirm`` edge (NEGOTIATION -> ORDER_CONFIRMED, OWNER) moves onto
  QUOTATION -> ORDER_CONFIRMED, and picks up the ``has_quotation_pdf``
  condition that used to live implicitly on the (now-deleted) ``negotiate``
  edge (0005): reaching NEGOTIATION always meant a PDF existed, so ``confirm``
  never needed its own check. Now that QUOTATION is reachable straight from
  ENQUIRY with no PDF requirement, ``confirm`` must carry that gate itself.
* ``negotiate`` (QUOTATION -> NEGOTIATION) is deleted outright — merged away.
* NEGOTIATION's ``rework -> QUOTATION`` would become a same-stage loop
  (forbidden by ``ck_transition_rules_loop``), so it is simply dropped.
  NEGOTIATION's ``lose -> LOST`` / ``cancel -> CANCELLED`` are now exact
  duplicates of the QUOTATION-sourced rules that already exist from 0003, so
  nothing new needs seeding for those actions.
* ``quote`` (ENQUIRY -> QUOTATION) gains ACCT, mirroring 0004's pattern: the
  PDF is typically attached by Accounts
  (``apps.sales.services.create_quotation_revision``), and
  ``_advance_lines_on_quotation_pdf`` calls ``perform_transition(actor, line,
  "quote")`` for every line still at ENQUIRY the moment a PDF lands — that
  call must succeed for an Accounts actor or the auto-advance silently no-ops
  for every card Accounts (not Sales/Owner) quotes.

NEGOTIATION's ``Stage`` row is deactivated, never deleted:
``fk_job_line_transitions_from/to`` are ``ON DELETE RESTRICT`` against
``pipeline.stages``, and that table is append-only audit history — any line
that ever historically moved into NEGOTIATION leaves a row that references it
forever. ``is_active = False`` is exactly what that flag is for
(``stages_for_module()`` already filters on it, so the column disappears from
the board and from ``available_actions`` for free, no other code change
needed).

Not safely reversible in full: ``unseed()`` restores the deleted rules, the
ACCT quote grant, and NEGOTIATION's ``is_active`` flag, but it does not move
reclassified lines back to NEGOTIATION — which specific lines those were is
not preserved.
"""

from django.db import migrations

from apps.identity.constants import ROLE_ACCT, ROLE_OWNER, ROLE_SALES

_STAGE_ENQUIRY = "ENQUIRY"
_STAGE_QUOTATION = "QUOTATION"
_STAGE_NEGOTIATION = "NEGOTIATION"
_STAGE_ORDER_CONFIRMED = "ORDER_CONFIRMED"
_STAGE_LOST = "LOST"
_STAGE_CANCELLED = "CANCELLED"

_HAS_PDF = "has_quotation_pdf"


def seed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    TransitionRule = apps.get_model("pipeline", "TransitionRule")
    Role = apps.get_model("identity", "Role")
    JobLine = apps.get_model("sales", "JobLine")

    quotation = Stage.objects.get(code=_STAGE_QUOTATION)
    negotiation = Stage.objects.get(code=_STAGE_NEGOTIATION)
    order_confirmed = Stage.objects.get(code=_STAGE_ORDER_CONFIRMED)
    enquiry = Stage.objects.get(code=_STAGE_ENQUIRY)

    JobLine.objects.filter(current_stage=negotiation).update(current_stage=quotation)

    # Re-home confirm: NEGOTIATION -> ORDER_CONFIRMED becomes
    # QUOTATION -> ORDER_CONFIRMED, gated on an actual quotation existing.
    TransitionRule.objects.filter(
        from_stage=negotiation, action_code="confirm"
    ).delete()
    owner = Role.objects.get(code=ROLE_OWNER)
    TransitionRule.objects.update_or_create(
        from_stage=quotation,
        action_code="confirm",
        allowed_role=owner,
        defaults={
            "to_stage": order_confirmed,
            "requires_note": False,
            "allow_self_approval": True,
            "condition_expr": _HAS_PDF,
            "is_active": True,
        },
    )

    # negotiate is merged away entirely.
    TransitionRule.objects.filter(
        from_stage=quotation, action_code="negotiate"
    ).delete()

    # rework/lose/cancel sourced from NEGOTIATION are now either a forbidden
    # self-loop or duplicates of the QUOTATION-sourced rules 0003 already
    # seeded — drop them, nothing to recreate.
    TransitionRule.objects.filter(
        from_stage=negotiation, action_code__in=["rework", "lose", "cancel"]
    ).delete()

    # quote gains ACCT, so an accountant's PDF upload can auto-advance a line
    # straight from ENQUIRY.
    TransitionRule.objects.update_or_create(
        from_stage=enquiry,
        action_code="quote",
        allowed_role=Role.objects.get(code=ROLE_ACCT),
        defaults={
            "to_stage": quotation,
            "requires_note": False,
            "allow_self_approval": True,
            "is_active": True,
        },
    )

    negotiation.is_active = False
    negotiation.save(update_fields=["is_active"])


def unseed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    TransitionRule = apps.get_model("pipeline", "TransitionRule")
    Role = apps.get_model("identity", "Role")

    quotation = Stage.objects.get(code=_STAGE_QUOTATION)
    negotiation = Stage.objects.get(code=_STAGE_NEGOTIATION)
    order_confirmed = Stage.objects.get(code=_STAGE_ORDER_CONFIRMED)
    enquiry = Stage.objects.get(code=_STAGE_ENQUIRY)
    lost = Stage.objects.get(code=_STAGE_LOST)
    cancelled = Stage.objects.get(code=_STAGE_CANCELLED)

    negotiation.is_active = True
    negotiation.save(update_fields=["is_active"])

    TransitionRule.objects.filter(from_stage=quotation, action_code="confirm").delete()
    TransitionRule.objects.update_or_create(
        from_stage=negotiation,
        action_code="confirm",
        allowed_role=Role.objects.get(code=ROLE_OWNER),
        defaults={
            "to_stage": order_confirmed,
            "requires_note": False,
            "allow_self_approval": True,
            "is_active": True,
        },
    )

    for role_code in [ROLE_SALES, ROLE_OWNER, ROLE_ACCT]:
        role = Role.objects.filter(code=role_code).first()
        if role is None:
            continue
        TransitionRule.objects.update_or_create(
            from_stage=quotation,
            action_code="negotiate",
            allowed_role=role,
            defaults={
                "to_stage": negotiation,
                "requires_note": False,
                "allow_self_approval": True,
                "condition_expr": _HAS_PDF,
                "is_active": True,
            },
        )

    for role_code in [ROLE_SALES, ROLE_OWNER]:
        role = Role.objects.get(code=role_code)
        TransitionRule.objects.update_or_create(
            from_stage=negotiation,
            action_code="rework",
            allowed_role=role,
            defaults={"to_stage": quotation, "requires_note": True, "allow_self_approval": True, "is_active": True},
        )
        TransitionRule.objects.update_or_create(
            from_stage=negotiation,
            action_code="lose",
            allowed_role=role,
            defaults={"to_stage": lost, "requires_note": True, "allow_self_approval": True, "is_active": True},
        )
        TransitionRule.objects.update_or_create(
            from_stage=negotiation,
            action_code="cancel",
            allowed_role=role,
            defaults={"to_stage": cancelled, "requires_note": True, "allow_self_approval": True, "is_active": True},
        )

    TransitionRule.objects.filter(
        from_stage=enquiry, action_code="quote", allowed_role__code=ROLE_ACCT
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0005_negotiate_requires_quotation_pdf"),
        ("sales", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
