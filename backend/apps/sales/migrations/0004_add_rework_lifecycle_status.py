"""Add "rework" as a real job-card lifecycle status.

Before this migration, a line going back to the pipeline's initial stage
via "Rework" (QUOTATION -> ENQUIRY) never touched
``job_cards.lifecycle_status`` at all —
``sync_job_card_status_from_lines()`` only cascades statuses that
``Stage.cascades_job_card_status`` names (won/lost/cancelled), and that
column is NULL for the initial stage. A reworked card's badge kept
showing "Quoted" everywhere (list, detail page, dashboard) even though
the line was back at square one awaiting a fresh quote, and there was no
way to filter the Job Cards list down to exactly those cards — the bug
report this migration and its matching ``apps.sales.services`` changes
fix.

Order matters: the schema ops widen ``ck_job_cards_lifecycle`` and
``idx_job_cards_open`` to allow/include ``rework`` *before* the
``RunPython`` step below writes that value into any row, exactly the
reverse ordering of migration 0002 (which had to reclassify data before
*narrowing* a domain).

The ``RunPython`` step is a one-time backfill for cards that were already
in this state before the code fix shipped — same "every active line is
back at the initial stage, and the card already has a quotation on file"
condition ``sync_job_card_status_from_lines()`` now applies going forward,
run once here against existing rows.

Not reversible: same reasoning as 0002 — there's nothing to restore a
back-filled row to (it was simply wrong before), so the reverse is a
documented no-op.
"""

from django.conf import settings
from django.db import migrations, models


def fix_already_reworked_cards(apps, schema_editor):
    JobCard = apps.get_model("sales", "JobCard")
    JobLine = apps.get_model("sales", "JobLine")
    Quotation = apps.get_model("sales", "Quotation")

    for card in JobCard.objects.filter(deleted_at__isnull=True).exclude(
        lifecycle_status="rework"
    ):
        lines = list(
            JobLine.objects.filter(job_card_id=card.id, deleted_at__isnull=True)
            .select_related("current_stage")
        )
        if not lines or not all(line.current_stage.is_initial for line in lines):
            continue
        if not Quotation.objects.filter(job_card_id=card.id).exists():
            continue

        card.lifecycle_status = "rework"
        card.save(update_fields=["lifecycle_status"])


def unfix(apps, schema_editor):
    """Not reversible — see module docstring."""


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0003_cli_client_code_sequence'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='jobcard',
            name='ck_job_cards_lifecycle',
        ),
        migrations.RemoveIndex(
            model_name='jobcard',
            name='idx_job_cards_open',
        ),
        migrations.AlterField(
            model_name='jobcard',
            name='lifecycle_status',
            field=models.TextField(choices=[('open', 'Open'), ('quoted', 'Quoted'), ('rework', 'Rework'), ('won', 'Won'), ('lost', 'Lost'), ('cancelled', 'Cancelled')], db_default='open', default='open'),
        ),
        migrations.AddIndex(
            model_name='jobcard',
            index=models.Index(condition=models.Q(('deleted_at__isnull', True), ('lifecycle_status__in', ['open', 'quoted', 'rework'])), fields=['owner_user', '-enquiry_date'], name='idx_job_cards_open'),
        ),
        migrations.AddConstraint(
            model_name='jobcard',
            constraint=models.CheckConstraint(condition=models.Q(('lifecycle_status__in', ['open', 'quoted', 'rework', 'won', 'lost', 'cancelled'])), name='ck_job_cards_lifecycle'),
        ),
        migrations.RunPython(fix_already_reworked_cards, unfix),
    ]
