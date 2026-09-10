"""Google Sheets ledger sync.

The office wants one always-current, human-readable table of every job card
instead of manual bookkeeping. This module owns exactly one thing: turning a
header row and data rows into a full overwrite of one Google Sheet. The row
data itself is business logic and lives in
``apps.sales.selectors.job_card_export_rows``; this module knows nothing
about job cards.

Full overwrite, not an incremental diff, on every call: ``sync_job_sheet``
runs on a timer (see ``docker-compose.yml``'s ``sheets-sync`` service), so
the job is self-healing rather than carrying dirty-tracking state that could
drift. The wipe is scoped to exactly the columns this sync owns (``A`` through
the last header column) — never the whole sheet — so office staff can add
their own columns past that (e.g. "Remarks", "Follow-up date") and those
survive every sync untouched. Anything hand-typed *inside* the synced columns
still doesn't survive; that block is the read-only mirror, the columns past
it are the organization's own space.

Formatting (cell padding, header bold/background, frozen row, column
widths) is re-applied on every sync, not just once, so it survives even a
worksheet that got deleted and recreated (``sheet.add_worksheet`` above).

# ponytail: the sheet grows forever (every non-deleted job card, no
# archiving) — fine at this company's likely volume; revisit with
# pagination only if row count ever approaches Sheets' ~10M-cell ceiling.
"""

from __future__ import annotations

import json

import gspread
from django.conf import settings
from gspread.utils import ValueInputOption, rowcol_to_a1

# The app's own accent color (frontend/src/styles/tokens.css: --h-accent: 222,
# hsl(222 72% 44%)), so the header matches the app instead of an invented color.
_HEADER_BACKGROUND = {"red": 31 / 255, "green": 80 / 255, "blue": 193 / 255}
_HEADER_TEXT = {"red": 1, "green": 1, "blue": 1}


def _client() -> gspread.Client:
    credentials = json.loads(settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
    return gspread.service_account_from_dict(credentials)


def sheet_url() -> str | None:
    """The human-facing edit URL for the configured spreadsheet, for the
    sidebar's link to it (``apps.identity.api.serialize_me``) — or ``None``
    if Google Sheets sync hasn't been configured yet (no spreadsheet ID),
    so a caller can hide the link entirely rather than offer a dead one."""
    sheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    if not sheet_id:
        return None
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def sync_rows(headers: list[str], rows: list[list]) -> int:
    """Overwrite the configured worksheet with ``headers`` followed by
    ``rows``. Both must already be flat lists of JSON-primitive values
    (``str`` / ``int`` / ``float``) — this function does no shaping or type
    coercion of its own. Returns the number of data rows written.

    Raises on any Google API failure (auth, missing sheet, quota, network).
    No retry here by design — the caller (the ``sync_job_sheet`` management
    command) exits non-zero on failure, and the next scheduled tick is the
    retry.
    """
    sheet = _client().open_by_key(settings.GOOGLE_SHEETS_SPREADSHEET_ID)
    name = settings.GOOGLE_SHEETS_WORKSHEET_NAME
    try:
        worksheet = sheet.worksheet(name)
    except gspread.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=name, rows=1, cols=max(len(headers), 1))

    # Only clear our own columns, down to the sheet's current row count (a
    # previous sync may have written more rows than this one does) — never
    # worksheet.clear(), which would also wipe any manual columns staff added
    # past our last header column.
    owned_range = f"A1:{rowcol_to_a1(max(worksheet.row_count, len(rows) + 1), len(headers))}"
    worksheet.batch_clear([owned_range])
    worksheet.update(values=[headers, *rows], value_input_option=ValueInputOption.user_entered)

    # Cell padding, not just column width, is what actually separates one
    # column's text from the next — auto-resize alone fits the column to the
    # text with no breathing room. Set padding *before* auto-resizing so the
    # resize accounts for it, on the whole written block (header + data), not
    # just the header.
    data_range = f"A1:{rowcol_to_a1(len(rows) + 1, len(headers))}"
    worksheet.format(data_range, {"padding": {"left": 8, "right": 8, "top": 4, "bottom": 4}})

    header_range = f"A1:{rowcol_to_a1(1, len(headers))}"
    worksheet.format(
        header_range,
        {
            "textFormat": {"bold": True, "foregroundColor": _HEADER_TEXT},
            "backgroundColor": _HEADER_BACKGROUND,
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        },
    )
    worksheet.freeze(rows=1)
    worksheet.columns_auto_resize(0, len(headers))

    return len(rows)
