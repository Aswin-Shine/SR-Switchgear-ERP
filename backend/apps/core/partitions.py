"""Quarterly partition management for ``core_audit_logs`` (D10).

The reference schema ships partitions for 2026 Q3 and Q4 only. After
2026-12-31 every insert into the seven audited tables would fail — not the
audit write alone, the *whole transaction*, because the trigger runs inside it.
A partition shortfall is therefore an outage of the application, not a
degradation of the audit trail.

Three things follow, and all three are implemented:

1. the migration creates partitions well ahead (through 2028-12-31);
2. ``manage.py ensure_audit_partitions`` extends the window idempotently;
3. the container entrypoint runs it after ``migrate``, every start.

No ``pg_partman``: a server extension for a problem this module solves in
about forty lines (BACKEND_PLAN.md section 7).
"""

from __future__ import annotations

from datetime import date

PARENT_TABLE = "core_audit_logs"

# Quarter index (1-4) -> (start month, end month exclusive, rolls into next year)
_QUARTER_BOUNDS = {
    1: ((1, 1), (4, 1), False),
    2: ((4, 1), (7, 1), False),
    3: ((7, 1), (10, 1), False),
    4: ((10, 1), (1, 1), True),
}


def quarter_of(d: date) -> tuple[int, int]:
    """Return ``(year, quarter)`` for a date."""
    return d.year, (d.month - 1) // 3 + 1


def next_quarter(year: int, quarter: int) -> tuple[int, int]:
    return (year + 1, 1) if quarter == 4 else (year, quarter + 1)


def partition_spec(year: int, quarter: int) -> tuple[str, str, str]:
    """Return ``(table_name, inclusive_lower_bound, exclusive_upper_bound)``."""
    (start_month, start_day), (end_month, end_day), rolls_over = _QUARTER_BOUNDS[quarter]
    end_year = year + 1 if rolls_over else year
    return (
        f"{PARENT_TABLE}_{year}_q{quarter}",
        f"{year:04d}-{start_month:02d}-{start_day:02d}",
        f"{end_year:04d}-{end_month:02d}-{end_day:02d}",
    )


def partition_ddl(year: int, quarter: int) -> str:
    """One ``CREATE TABLE IF NOT EXISTS ... PARTITION OF`` statement.

    ``IF NOT EXISTS`` is what lets the migration and the management command
    share these statements without either having to know what the other did.
    """
    name, lower, upper = partition_spec(year, quarter)
    return (
        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF {PARENT_TABLE}\n"
        f"    FOR VALUES FROM ('{lower}') TO ('{upper}');"
    )


def quarters_from(start: date, count: int) -> list[tuple[int, int]]:
    """``count`` quarters beginning with the one containing ``start``."""
    year, quarter = quarter_of(start)
    out = []
    for _ in range(count):
        out.append((year, quarter))
        year, quarter = next_quarter(year, quarter)
    return out


def partitions_through(start: date, end: date) -> list[tuple[int, int]]:
    """Every quarter from the one containing ``start`` to the one containing ``end``."""
    year, quarter = quarter_of(start)
    end_year, end_quarter = quarter_of(end)
    out = []
    while (year, quarter) <= (end_year, end_quarter):
        out.append((year, quarter))
        year, quarter = next_quarter(year, quarter)
    return out


def ddl_for(quarters: list[tuple[int, int]]) -> str:
    return "\n".join(partition_ddl(year, quarter) for year, quarter in quarters)


# The window the initial migration opens: the schema's own starting quarter
# through 2028-12-31 (D10).
INITIAL_PARTITIONS = partitions_through(date(2026, 7, 1), date(2028, 12, 31))
INITIAL_PARTITION_DDL = ddl_for(INITIAL_PARTITIONS)
