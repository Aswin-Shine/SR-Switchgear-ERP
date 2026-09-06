"""A line reaching CANCELLED or LOST now cascades its card's lifecycle_status.

Adds ``pipeline_stages.cascades_job_card_status`` — nullable, so every
stage but CANCELLED/LOST is unaffected — and seeds ``"cancelled"`` /
``"lost"`` on those two rows. A plain string, not a reference to
``apps.sales.models.JobLifecycleStatus``: ``pipeline`` must not import
``sales`` (dependency direction is sales -> pipeline -> identity -> hr ->
core), so this column is deliberately opaque at this layer. The
``ck_stages_cascade_status`` CHECK is the DB-level guard on its domain,
mirroring how ``ck_job_cards_lifecycle`` guards ``lifecycle_status``
itself — not a Python literal comparison.

``apps.sales.signals`` (new) listens for ``pipeline.JobLineTransition``
being created and calls ``apps.sales.services.sync_job_card_status_from_lines``,
which reads this column to decide whether every active line on a card now
agrees on the same outcome. This is the layering-safe way to let a
Sales-domain field (``job_cards.lifecycle_status``) react to a pipeline
event without pipeline ever importing or knowing about Sales — sales
already depends on pipeline, so a receiver living in ``apps/sales`` is the
standard Django pattern for it.

ORDER_CONFIRMED is deliberately left unseeded here (no "won" cascade):
that outcome is already governed by
``apps.sales.services.record_quotation_outcome``, a more rigorous business
event (the client formally accepted a quotation) that a line simply
reaching Order-Confirmed on the board doesn't guarantee.

Same seed/unseed shape as 0004/0005/0007, scoped to exactly these two rows.
"""

from django.db import migrations, models

_SEED = {"CANCELLED": "cancelled", "LOST": "lost"}


def seed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    for code, outcome in _SEED.items():
        Stage.objects.filter(code=code).update(cascades_job_card_status=outcome)


def unseed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    Stage.objects.filter(code__in=_SEED).update(cascades_job_card_status=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_database_objects"),
        ("pipeline", "0007_cancelled_hides_from_board_after_3_hours"),
    ]

    operations = [
        migrations.AddField(
            model_name="stage",
            name="cascades_job_card_status",
            field=models.CharField(
                blank=True,
                help_text="When every active line on a card reaches a stage sharing "
                "this value, the card's own lifecycle_status is set to match (see "
                "apps.sales.signals). A plain string mirroring "
                "apps.sales.models.JobLifecycleStatus's values without importing "
                "it — pipeline stays ignorant of sales. NULL means this stage "
                "carries no card-level outcome.",
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="stage",
            constraint=models.CheckConstraint(
                condition=models.Q(("cascades_job_card_status__isnull", True))
                | models.Q(("cascades_job_card_status__in", ["won", "lost", "cancelled"])),
                name="ck_stages_cascade_status",
            ),
        ),
        migrations.RunPython(seed, unseed),
    ]
