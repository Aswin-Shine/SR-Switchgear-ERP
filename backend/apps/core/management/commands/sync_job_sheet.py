"""Push the whole job-card ledger to the office's Google Sheet.

Run on a timer by the ``sheets-sync`` service in ``docker-compose.yml`` —
every 5 hours, full overwrite, not incremental. See ``apps.core.sheets`` for
why a full overwrite is deliberate, and
``apps.sales.selectors.job_card_sheet_rows`` for the column order and cell
formatting (shared with the manual "Sync now" button's API endpoint,
``apps.sales.api.sync_job_sheet``, so the two can't drift apart).

Any failure here (bad credentials, sheet not shared with the service
account, network, Google API quota) raises ``CommandError`` so the process
exits non-zero. The sidecar's shell loop swallows that (``|| true``) so one
bad run doesn't crash-loop the container — the next tick, 5 hours later, is
the retry. No retry/backoff logic belongs in this command.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.sheets import sync_rows
from apps.sales.selectors import job_card_sheet_rows


class Command(BaseCommand):
    help = "Overwrite the Google Sheets job-card ledger with the current data."

    def handle(self, *args, **options):
        headers, rows = job_card_sheet_rows()

        try:
            written = sync_rows(headers, rows)
        except Exception as exc:
            raise CommandError(f"Google Sheets sync failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Synced {written} job card(s) to the sheet."))
