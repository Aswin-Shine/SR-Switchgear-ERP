"""Field types and database functions Django does not ship, but the schema needs.

Each one exists because of a measured gap between what
``docs/schema/sr_erp_schema_v2.sql`` declares and what Django 5.2 emits. The
gaps are catalogued in BACKEND_PLAN.md section 3 and were verified against
Django 5.2.17 / PostgreSQL 16 rather than assumed.

Importing this module registers the ``length`` lookup on ``TextField``. Models
must not be imported before it (``apps/core/models.py`` imports it first, and
every other app's models import from core).
"""

import uuid

from django.db.models import CharField, Func, TextField
from django.db.models.functions import Length

# Deviation 3.2 — the schema has CHECK (length(username) BETWEEN 3 AND 64), but
# Q(username__length__gte=3) raises FieldError: Unsupported lookup 'length'.
# The transform exists; Django just does not register it by default.
TextField.register_lookup(Length)
CharField.register_lookup(Length)


class CITextField(TextField):
    """A real PostgreSQL ``citext`` column.

    Deviation 3.1. ``django.contrib.postgres.fields.CITextField`` still imports
    but is a removed shim that fails system check ``fields.E907``. Django's own
    hint is to use a non-deterministic collation instead — which PostgreSQL
    refuses to combine with regex operators, and ``ck_employees_email`` is a
    regex CHECK on a citext column. So the shim's advice is unusable here and
    this eight-line field is the honest fix.

    Subclassing TextField (not CharField) keeps the registered ``length``
    lookup applicable, which ``ck_user_accounts_username`` depends on.

    That choice has one sharp edge: ``CharField.formfield()`` sets
    ``empty_value=None`` for a nullable field so a blank form submission
    cleans to ``None``; ``TextField.formfield()`` never does this — an empty
    ``Textarea`` always cleans to ``""`` regardless of ``null=True``. That
    silently broke ``ck_employees_email`` (NULL-or-valid-regex): leaving
    ``personal_email`` blank in the admin sent ``""``, which is neither NULL
    nor a valid address, and the form rejected it with a raw constraint-name
    error. Every current use of this field (``Employee.personal_email``,
    ``Client.email``) is exactly that null=True, blank=True, "empty means
    absent" shape, so this mirrors ``CharField``'s own handling rather than
    special-casing it per admin form.
    """

    def db_type(self, connection) -> str:
        return "citext"

    def rel_db_type(self, connection) -> str:
        # Foreign keys pointing at a citext column must themselves be citext.
        return "citext"

    def formfield(self, **kwargs):
        from django.db import connection

        if self.null and not connection.features.interprets_empty_strings_as_nulls:
            kwargs.setdefault("empty_value", None)
        return super().formfield(**kwargs)


class FixedCharField(CharField):
    """A blank-padded ``char(n)`` column.

    Deviation 3.5. ``CharField(max_length=n)`` emits ``varchar(n)``. The schema
    uses ``CHAR(64)`` for ``sha256`` and ``CHAR(3)`` for ``currency``, and the
    difference is visible: ``char`` pads on read.
    """

    def db_type(self, connection) -> str:
        return f"char({self.max_length})"


class Now(Func):
    """``NOW()``, not ``statement_timestamp()``.

    Deviation 3.3. Django's own ``functions.Now`` emits
    ``statement_timestamp()``. Inside a single transaction the two differ:
    ``NOW()`` is the transaction start, ``statement_timestamp()`` is per
    statement. The schema says ``DEFAULT NOW()``, so rows inserted in one
    transaction should share a timestamp.
    """

    template = "NOW()"
    output_field = None  # set by the field using it

    def __init__(self, output_field=None, **extra):
        super().__init__(output_field=output_field, **extra)


class RandomUUID(Func):
    """``gen_random_uuid()``.

    Deviation 3.4. Django generates UUIDs in Python and emits no database
    default. Models pair this ``db_default`` with ``default=uuid.uuid4`` so that
    rows inserted straight from ``psql`` — the bootstrap command, a data fix,
    the audit trigger's own inserts — still get keys.
    """

    template = "GEN_RANDOM_UUID()"
    output_field = None

    def __init__(self, output_field=None, **extra):
        super().__init__(output_field=output_field, **extra)


def uuid_pk_kwargs() -> dict:
    """The dual default from deviation 3.4, in one place."""
    return {
        "primary_key": True,
        "default": uuid.uuid4,
        "db_default": RandomUUID(),
        "editable": False,
    }
