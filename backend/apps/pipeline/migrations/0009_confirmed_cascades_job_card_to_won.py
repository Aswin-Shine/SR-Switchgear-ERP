"""ORDER_CONFIRMED cascades its card's lifecycle_status to "won".

Companion to the quotation-status-machine removal
(``sales/migrations/0002_remove_quotation_status_machine.py``): that
migration deletes ``record_quotation_outcome``, the only thing that ever
set a card to "won". This is its replacement, seeded exactly like
CANCELLED/LOST already are (migration 0008) — no code change needed,
``apps.sales.services.sync_job_card_status_from_lines`` already handles any
value found on ``Stage.cascades_job_card_status`` generically. Pressing
"Confirm" on the pipeline board is the real signal in this system's actual
process, so that's what now drives "won".
"""

from django.db import migrations

_STAGE_CODE = "ORDER_CONFIRMED"
_OUTCOME = "won"


def seed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    Stage.objects.filter(code=_STAGE_CODE).update(cascades_job_card_status=_OUTCOME)


def unseed(apps, schema_editor):
    Stage = apps.get_model("pipeline", "Stage")
    Stage.objects.filter(code=_STAGE_CODE).update(cascades_job_card_status=None)


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0008_cancelled_and_lost_cascade_job_card_status"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
