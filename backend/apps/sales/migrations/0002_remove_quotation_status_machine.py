"""Remove the D7 quotation status machine (activate/send/accept/lose).

The real process this system supports turned out not to need it: ACCT
uploads a priced PDF; that upload is immediately the thing Sales downloads
and sends to the client themselves, outside this system; if the client
rejects it, Sales presses "Rework" on the pipeline board and ACCT uploads a
revised PDF. There is no in-app activate/send/accept step.

Order matters here — the data must be reclassified *before* the new,
narrower ``ck_quotations_status`` CHECK is added, or the `AddConstraint`
below fails against any existing row still in a status this migration is
about to make invalid. Every quotation in ``active``/``sent``/``accepted``/
``lost`` becomes ``draft``: under the old model none of them had a
superseding successor (that's what those statuses meant), so under the new
one they're all correctly "the current revision for their card" — exactly
what ``draft`` now means. Only rows already ``superseded`` stay that way.
Not reversible in the sense of recovering which of the four original
statuses a row had — the seed's own `unseed()` is a no-op for that reason,
matching how migration ``0008`` (pipeline) already documents an
irreversible reclassification.

``sent_by``/``sent_at`` are dropped outright — nothing tracks "who sent it
and when" anymore. ``ck_quotations_pdf_needed``, ``ck_quotations_sent`` and
``uk_quotations_one_active`` all encoded rules for statuses that no longer
exist. ``pdf_document_id`` stays nullable at the DB level even though
``apps.sales.services.create_quotation_revision`` now requires a PDF for
every *new* revision — enforced in Python, not a NOT NULL migration, so
existing rows created before this fix (some may have none) don't need a
backfill decision.
"""

from django.conf import settings
from django.db import migrations, models

_OLD_LIVE_STATUSES = ["active", "sent", "accepted", "lost"]


def reclassify_removed_statuses(apps, schema_editor):
    Quotation = apps.get_model("sales", "Quotation")
    Quotation.objects.filter(status__in=_OLD_LIVE_STATUSES).update(status="draft")


def unseed(apps, schema_editor):
    # Not safely reversible: which of the four original statuses each row
    # had is not preserved. See the module docstring.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_database_objects"),
        ("sales", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(reclassify_removed_statuses, unseed),
        migrations.RemoveConstraint(
            model_name="quotation",
            name="ck_quotations_status",
        ),
        migrations.RemoveConstraint(
            model_name="quotation",
            name="ck_quotations_sent",
        ),
        migrations.RemoveConstraint(
            model_name="quotation",
            name="ck_quotations_pdf_needed",
        ),
        migrations.RemoveConstraint(
            model_name="quotation",
            name="uk_quotations_one_active",
        ),
        migrations.RemoveField(
            model_name="quotation",
            name="sent_at",
        ),
        migrations.RemoveField(
            model_name="quotation",
            name="sent_by",
        ),
        migrations.AlterField(
            model_name="quotation",
            name="status",
            field=models.TextField(
                choices=[("draft", "Draft"), ("superseded", "Superseded")],
                db_default="draft",
                default="draft",
            ),
        ),
        migrations.AddConstraint(
            model_name="quotation",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["draft", "superseded"])),
                name="ck_quotations_status",
            ),
        ),
    ]
