"""Database helpers. Chiefly: who the audit trigger should blame.

``core.record_audit()`` reads the actor from ``current_setting('app.current_user_id', TRUE)``.
Something has to set it. That something is ``audit_actor()``.

This lands in Phase 1, not Phase 6, because every audit assertion in the test
suite depends on it. The Phase 6 middleware is a thin caller of this function,
not a reimplementation.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from django.db import connection, transaction

# The GUC the audit trigger reads. Named here once so a rename cannot drift
# between the raw SQL and the Python.
ACTOR_SETTING = "app.current_user_id"


@contextlib.contextmanager
def audit_actor(user: Any | None) -> Iterator[None]:
    """Open a transaction and attribute every audited write inside it to ``user``.

    ``SET LOCAL`` rather than ``SET`` is deliberate and load-bearing. PgBouncer
    in transaction mode hands the same backend connection to a different client
    after each transaction; a plain ``SET`` would leak this actor to whoever
    borrows the connection next, and the audit trail would name the wrong
    person. ``SET LOCAL`` is discarded at COMMIT or ROLLBACK.

    ``user`` of ``None`` (a management command, a data migration, the
    bootstrap) leaves the setting empty, and the trigger records
    ``changed_by IS NULL``. That is a truthful "no authenticated actor", not a
    failure.

    The previous value is saved and restored on exit. This matters more than it
    looks: ``SET LOCAL`` is scoped to the *transaction*, not to the savepoint
    that a nested ``atomic()`` opens, so without the restore an inner
    ``audit_actor(B)`` would keep attributing writes to B for the rest of the
    outer transaction after the block had closed. With ``ATOMIC_REQUESTS =
    True`` the outer transaction is the whole request, so that would misattribute
    every subsequent write in it. On the exception path no restore is needed —
    rolling back to the savepoint discards the setting too.
    """
    with transaction.atomic():
        previous = _read_actor()
        _write_actor(getattr(user, "pk", None) if user is not None else None)
        try:
            yield
        except Exception:
            raise
        else:
            _write_actor(previous)


def _write_actor(user_id) -> None:
    with connection.cursor() as cursor:
        if user_id is None:
            # SET LOCAL will not accept a bound NULL, and the trigger treats ''
            # as absent via NULLIF.
            cursor.execute(f"SET LOCAL {ACTOR_SETTING} = ''")
        else:
            # The GUC name cannot be parameterised; the value must be.
            cursor.execute(f"SET LOCAL {ACTOR_SETTING} = %s", [str(user_id)])


def _read_actor() -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT NULLIF(current_setting('{ACTOR_SETTING}', TRUE), '')")
        return cursor.fetchone()[0]


def current_audit_actor() -> str | None:
    """Read back the actor. For assertions and debugging, not for logic."""
    return _read_actor()
