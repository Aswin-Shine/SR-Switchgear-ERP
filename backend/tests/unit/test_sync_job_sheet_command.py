"""``sync_job_sheet`` — mocks apps.core.sheets.sync_rows at the boundary
(the actual Google API call), the same way the real command is isolated
from Google's availability. Nothing here talks to a real spreadsheet."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands import sync_job_sheet
from tests.factories import JobCardFactory


@pytest.mark.django_db
def test_it_pushes_headers_and_one_row_per_card(monkeypatch):
    JobCardFactory()
    JobCardFactory()
    captured = {}

    def fake_sync_rows(headers, rows):
        captured["headers"] = headers
        captured["rows"] = rows
        return len(rows)

    monkeypatch.setattr(sync_job_sheet, "sync_rows", fake_sync_rows)

    call_command("sync_job_sheet")

    assert captured["headers"] == sync_job_sheet.HEADERS
    assert len(captured["rows"]) == 2
    assert all(len(row) == len(sync_job_sheet.HEADERS) for row in captured["rows"])


@pytest.mark.django_db
def test_a_sync_failure_surfaces_as_a_command_error(monkeypatch):
    JobCardFactory()

    def failing_sync_rows(headers, rows):
        raise RuntimeError("permission denied: sheet not shared with service account")

    monkeypatch.setattr(sync_job_sheet, "sync_rows", failing_sync_rows)

    with pytest.raises(CommandError, match="permission denied"):
        call_command("sync_job_sheet")
