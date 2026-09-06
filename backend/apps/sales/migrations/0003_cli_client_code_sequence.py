"""Renumber every existing client_code into the CLI-NNN sequence.

Same story as hr/migrations/0002_srs_employee_code_sequence: client_code
was free text, hand-typed both in the Django admin and in the SPA's
"New client" dialog. Real data drifted accordingly (DEMO001, DEMO0002,
DEM003, 1234 — no consistent shape at all). apps.sales.services.create_client
and ClientAdmin now always call apps.core.numbering.next_client_code(), and
the SPA's NewClientDialog no longer collects a code at all.

This migration folds the existing rows into that same sequence, oldest
first by created_at, calling next_client_code() for each row so the
renumbering and the core_number_series counter it seeds are the exact same
call path a new client goes through.

Not reversible: the original codes are gone once overwritten, and there is
no record of which row had which — same shape as
hr/migrations/0002_srs_employee_code_sequence.
"""

from __future__ import annotations

from django.db import migrations

from apps.core.numbering import next_client_code


def renumber(apps, schema_editor):
    Client = apps.get_model("sales", "Client")
    for client in Client.objects.order_by("created_at"):
        client.client_code = next_client_code()
        client.save(update_fields=["client_code"])


def unrenumber(apps, schema_editor):
    """Not reversible — see module docstring."""


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0002_remove_quotation_status_machine"),
    ]

    operations = [
        migrations.RunPython(renumber, unrenumber),
    ]
