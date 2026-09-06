"""Cross-app reaction to pipeline transitions.

Sales listens; pipeline never imports sales (dependency direction is
sales -> pipeline -> identity -> hr -> core). ``pipeline.JobLineTransition``
rows are created in exactly one place in the codebase
(``apps.pipeline.services.perform_transition``), always through the ORM, so
a ``post_save`` signal here is reliable — this is a different concern from
the audit trail's "triggers, not signals" note, which exists specifically
to catch writes that bypass the ORM entirely.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.pipeline.models import JobLineTransition


@receiver(post_save, sender=JobLineTransition)
def sync_job_card_status_from_line_transition(sender, instance, created, **kwargs):
    if not created:
        return
    from apps.sales.services import sync_job_card_status_from_lines

    sync_job_card_status_from_lines(instance.job_line.job_card_id)
