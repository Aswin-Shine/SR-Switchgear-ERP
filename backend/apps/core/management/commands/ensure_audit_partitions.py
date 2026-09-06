"""Keep ``core_audit_logs`` partitioned far enough into the future (D10).

Run from the container entrypoint alongside ``migrate``, every start. It is
idempotent — every statement is ``CREATE TABLE IF NOT EXISTS`` — so running it
on every boot of every replica is harmless.

Why this matters more than it looks: the audit triggers fire inside the
caller's transaction. A missing partition does not merely lose an audit row, it
aborts the business transaction that provoked it. Running out of partitions is
an outage.
"""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from apps.core.partitions import PARENT_TABLE, partition_ddl, partition_spec, quarters_from


class Command(BaseCommand):
    help = "Create any missing quarterly partitions for core_audit_logs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--quarters-ahead",
            type=int,
            default=settings.AUDIT_PARTITION_QUARTERS_AHEAD,
            help="How many quarters from today to keep open (default from settings).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the DDL that would run and change nothing.",
        )

    def handle(self, *args, **options):
        quarters_ahead: int = options["quarters_ahead"]
        dry_run: bool = options["dry_run"]

        if quarters_ahead < 1:
            self.stderr.write("--quarters-ahead must be at least 1")
            return

        wanted = quarters_from(date.today(), quarters_ahead)
        existing = self._existing_partitions()

        created = []
        for year, quarter in wanted:
            name, lower, upper = partition_spec(year, quarter)
            if name in existing:
                continue
            ddl = partition_ddl(year, quarter)
            if dry_run:
                self.stdout.write(ddl)
            else:
                with connection.cursor() as cursor:
                    cursor.execute(ddl)
            created.append(f"{name} [{lower} .. {upper})")

        if not created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{PARENT_TABLE}: {len(wanted)} quarters already covered, nothing to do."
                )
            )
            return

        verb = "Would create" if dry_run else "Created"
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(created)} partition(s):"))
        for line in created:
            self.stdout.write(f"  {line}")

    def _existing_partitions(self) -> set[str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.relname
                FROM pg_inherits i
                JOIN pg_class c ON c.oid = i.inhrelid
                WHERE i.inhparent = %s::regclass
                """,
                [PARENT_TABLE],
            )
            return {row[0] for row in cursor.fetchall()}
