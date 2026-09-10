"""Push the whole job-card ledger to the office's Google Sheet.

Run on a timer by the ``sheets-sync`` service in ``docker-compose.yml`` —
every 5 hours, full overwrite, not incremental. See ``apps.core.sheets`` for
why a full overwrite is deliberate, and
``apps.sales.selectors.job_card_export_rows`` for what a row actually
contains.

Any failure here (bad credentials, sheet not shared with the service
account, network, Google API quota) raises ``CommandError`` so the process
exits non-zero. The sidecar's shell loop swallows that (``|| true``) so one
bad run doesn't crash-loop the container — the next tick, 5 hours later, is
the retry. No retry/backoff logic belongs in this command.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.sheets import sync_rows
from apps.sales.selectors import job_card_export_rows

HEADERS = [
    "Job No",
    "Client",
    "Client Code",
    "Status",
    "Enquiry Date",
    "Required By",
    "Owner",
    "Lines",
    "Quotation No",
    "Quotation Rev",
    "Quotation Status",
    "Quoted Amount",
    "Valid Till",
    "Quotation PDF",
    "Attachments",
]


def _cell(value) -> str:
    """Every gspread cell is a JSON-primitive string — dates, Decimals, and
    None all need to become plain text, not left as Python objects."""
    if value is None or value == "":
        return ""
    return str(value)


def _row(data: dict) -> list[str]:
    return [
        _cell(data["job_no"]),
        _cell(data["client_legal_name"]),
        _cell(data["client_code"]),
        _cell(data["lifecycle_status"]).replace("_", " ").title(),
        _cell(data["enquiry_date"]),
        _cell(data["required_by"]),
        _cell(data["owner_username"]),
        _cell(data["line_count"]),
        _cell(data["quotation_no"]),
        _cell(data["quotation_revision"]),
        _cell(data["quotation_status"]).replace("_", " ").title(),
        _cell(data["quoted_amount"]),
        _cell(data["valid_till"]),
        _cell(data["quotation_pdf_filename"]),
        _cell(data["attachment_filenames"]),
    ]


class Command(BaseCommand):
    help = "Overwrite the Google Sheets job-card ledger with the current data."

    def handle(self, *args, **options):
        rows = job_card_export_rows()
        sheet_rows = [_row(row) for row in rows]

        try:
            written = sync_rows(HEADERS, sheet_rows)
        except Exception as exc:
            raise CommandError(f"Google Sheets sync failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Synced {written} job card(s) to the sheet."))
