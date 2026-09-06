"""Cancelled lines disappear from the board 3 hours after cancellation.

Adds ``pipeline_stages.board_hide_after_hours`` — nullable, so every stage
except CANCELLED stays unaffected — and seeds it to 3 on CANCELLED. The
board query (``apps.pipeline.selectors.board_visible_lines``) drops a line
from ``GET /api/v1/board`` once this many hours have passed since its last
transition, computed live on every read rather than by a scheduled job:
nothing in this repo runs Celery/cron, and a presentational "stop showing
old cancelled stuff" rule doesn't need that infrastructure.

Nothing is deleted here or by the selector that reads this value — the job
line, its card, and its full transition history are untouched. This is the
same "stages are data" pattern as ``is_terminal``/``is_active``
(0001/0002), not a literal stage code anywhere in application logic.

Same seed/unseed shape as 0004/0005, scoped to exactly the CANCELLED row.
"""

from django.db import migrations, models

_STAGE_CODE = "CANCELLED"
_HOURS = 3


def seed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    Stage.objects.filter(code=_STAGE_CODE).update(board_hide_after_hours=_HOURS)


def unseed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    Stage.objects.filter(code=_STAGE_CODE).update(board_hide_after_hours=None)


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0006_merge_negotiation_into_quotation"),
    ]

    operations = [
        migrations.AddField(
            model_name="stage",
            name="board_hide_after_hours",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Hours after a line enters this stage before it stops "
                "appearing on GET /api/v1/board. NULL means never hidden. "
                "Nothing is deleted — this only affects the board query.",
                null=True,
            ),
        ),
        migrations.RunPython(seed, unseed),
    ]
