"""Business number issuance.

Wraps ``core.next_number()``. The counter lives in ``core_number_series``, one
row per prefix, incremented under a row lock — so two concurrent transactions
cannot receive the same number.

D6: calendar year, in the prefix. ``JOB-2026-`` and ``JOB-2027-`` are separate
rows, so the counter resets when the year turns without anybody having to
remember to reset it. The worked example in the schema review is
``JOB-2026-00001``, and note that ``next_number`` concatenates the prefix
directly — the trailing hyphen is part of the prefix, not added by the function.

Job and quotation numbers additionally carry a 3-letter month abbreviation:
``JOB-2026-SEP-00001``. That month is spliced into the *string* only, in
``_next_dated_number`` below — the counter key stays ``JOB-2026-``/``QT-2026-``
(year only, unchanged). This is deliberate: the serial keeps incrementing
across the whole year rather than resetting each month, so the key it's
issued under must not change when the month turns. Do not "simplify" this by
folding the month into the key passed to ``next_number`` — that would give
each month its own counter row starting back at 1, which is exactly the
per-month reset this format does not want.

On gaps — the schema comment and BACKEND_PLAN.md section 11 both say a
rolled-back transaction leaves a hole. Measured against PostgreSQL 16, it does
not. That warning is true of a ``SEQUENCE``, whose ``nextval`` is deliberately
non-transactional, but ``next_number()`` is an ordinary ``UPDATE`` of a row in
``core_number_series``, and an ordinary UPDATE rolls back with its transaction.
Concurrent callers serialise on the counter row and the loser reuses the
number the aborted transaction gave up.

So the guarantee is stronger than advertised: gapless, at the cost of one row
lock per prefix. Fine at this volume. Recorded here — and pinned by
``tests/integration/test_numbering_concurrency.py`` — because someone reading
only the comment might "fix" the imagined gap by switching to a sequence, and
introduce the very gaps the comment warns about.
"""

from __future__ import annotations

from datetime import date

from django.db import connection

JOB_PREFIX = "JOB"
QUOTATION_PREFIX = "QT"
DEFAULT_WIDTH = 5

#: Explicit, not ``date.strftime("%b")`` — must not depend on the server's locale.
MONTH_ABBR = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

#: No year component — unlike JOB/QT, an employee code is never reissued
#: per calendar year, so this is one row in core_number_series forever.
EMPLOYEE_PREFIX = "SRS-"
EMPLOYEE_CODE_WIDTH = 3

#: Distinct from EMPLOYEE_PREFIX so a client code and an employee code are
#: never visually interchangeable. No year component, same reasoning.
CLIENT_PREFIX = "CLI-"
CLIENT_CODE_WIDTH = 3


def next_number(prefix: str, width: int = DEFAULT_WIDTH) -> str:
    """Issue the next number for ``prefix``."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT next_number(%s, %s)", [prefix, width])
        return cursor.fetchone()[0]


def year_prefix(stem: str, on: date | None = None) -> str:
    """``JOB`` -> ``JOB-2026-`` for the calendar year of ``on`` (default today)."""
    year = (on or date.today()).year
    return f"{stem}-{year}-"


def _next_dated_number(stem: str, on: date | None) -> str:
    """``next_number()``'s counter key stays year-only (unchanged) so the
    serial keeps incrementing across the whole year; the month is spliced
    into the *returned* string only, purely for display."""
    d = on or date.today()
    prefix = year_prefix(stem, d)
    raw = next_number(prefix)
    serial = raw.removeprefix(prefix)
    return f"{prefix}{MONTH_ABBR[d.month - 1]}-{serial}"


def next_job_no(on: date | None = None) -> str:
    return _next_dated_number(JOB_PREFIX, on)


def next_quotation_no(on: date | None = None) -> str:
    return _next_dated_number(QUOTATION_PREFIX, on)


def next_employee_code() -> str:
    """``SRS-001``, ``SRS-002``, ... — the only way an employee_code is ever
    produced. Callers never supply one; see ``apps.hr.services.create_employee``
    and ``EmployeeAdmin.save_model``."""
    return next_number(EMPLOYEE_PREFIX, EMPLOYEE_CODE_WIDTH)


def next_client_code() -> str:
    """``CLI-001``, ``CLI-002``, ... — the only way a client_code is ever
    produced. Callers never supply one; see ``apps.sales.services.create_client``,
    ``ClientAdmin.save_model``, and the SPA's ``NewClientDialog`` (which no
    longer collects a code at all)."""
    return next_number(CLIENT_PREFIX, CLIENT_CODE_WIDTH)
