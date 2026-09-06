"""core — shared reference data, documents, numbering, audit.

Tables: core_departments, core_designations, core_documents,
core_number_series, core_audit_logs.

Conventions that hold across all five apps:

* ``db_table`` is set explicitly on every model. Django's default
  ``<app>_<model>`` would give ``core_department`` (singular); the schema
  pluralises.
* ``default_permissions = ()`` on every model. Authorisation is ours, in
  auth_roles / auth_permissions, and Django's ``auth_permission`` table must
  not fill up with rows nothing reads (deviation 3.11).
* Every ``ForeignKey`` is ``db_constraint=False, db_index=False``. Django emits
  deferrable FKs with no ``ON DELETE`` clause and adds a duplicate index on
  every FK column (deviations 3.6, 3.7). The real FKs and the schema's named
  ``idx_*`` indexes are created in ``core/migrations/0003_database_objects.py``
  and ``Meta.indexes`` respectively. ``on_delete`` still matters — it is
  Django's in-Python collector, and it is set to agree with the database's own
  action in every case.
* Soft delete is a plain ``deleted_at`` column. Managers are deliberately NOT
  overridden to hide soft-deleted rows: an invisible default filter breaks the
  admin and hides referential reality. ``selectors.py`` applies
  ``deleted_at IS NULL`` explicitly, matching the partial indexes.
"""

from __future__ import annotations

import uuid

from django.db import models

# Importing fields registers the `length` lookup. Must happen before any model
# class body that uses `__length` in a constraint is evaluated.
from apps.core.fields import (  # noqa: F401
    CITextField,
    FixedCharField,
    Now,
    RandomUUID,
    uuid_pk_kwargs,
)


def fk(to: str, on_delete, **kwargs) -> models.ForeignKey:
    """A ForeignKey that leaves the constraint and the index to the schema."""
    kwargs.setdefault("db_constraint", False)
    kwargs.setdefault("db_index", False)
    return models.ForeignKey(to, on_delete=on_delete, **kwargs)


class TimeStamped(models.Model):
    """created_at / updated_at. updated_at is maintained by set_updated_at()."""

    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        abstract = True


class SoftDelete(models.Model):
    """A nullable deleted_at. See the module docstring on why no manager hides it."""

    deleted_at = models.DateTimeField(null=True, blank=True, default=None)

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class Department(TimeStamped, SoftDelete):
    """Organisational units. Self-referencing for sub-departments."""

    id = models.UUIDField(**uuid_pk_kwargs())
    code = CITextField()
    name = models.TextField()
    parent_department = fk(
        "self", models.PROTECT, null=True, blank=True, related_name="children"
    )
    is_active = models.BooleanField(db_default=True, default=True)

    class Meta:
        db_table = "core_departments"
        default_permissions = ()
        verbose_name = "department"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uk_departments_code"),
            # IS DISTINCT FROM semantics: ~Q(a=F("id")) emits
            # NOT (a = id AND a IS NOT NULL), which is true when a is NULL.
            models.CheckConstraint(
                condition=~models.Q(parent_department=models.F("id")),
                name="ck_departments_not_self",
            ),
        ]
        indexes = [
            models.Index(fields=["parent_department"], name="idx_departments_parent"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Designation(TimeStamped, SoftDelete):
    """Job titles, kept separate from department so titles can be reused."""

    id = models.UUIDField(**uuid_pk_kwargs())
    code = CITextField()
    name = models.TextField()
    is_active = models.BooleanField(db_default=True, default=True)

    class Meta:
        db_table = "core_designations"
        default_permissions = ()
        verbose_name = "designation"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uk_designations_code"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Document(SoftDelete):
    """Metadata for an uploaded file. The bytes live in object storage.

    Never store the file itself here. ``storage_key`` addresses it.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    storage_key = models.TextField()
    original_filename = models.TextField()
    mime_type = models.TextField()
    byte_size = models.BigIntegerField()
    sha256 = FixedCharField(max_length=64, null=True, blank=True)
    uploaded_by = fk(
        "identity.UserAccount",
        models.PROTECT,
        db_column="uploaded_by",
        related_name="uploaded_documents",
    )
    uploaded_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "core_documents"
        default_permissions = ()
        verbose_name = "document"
        constraints = [
            models.UniqueConstraint(fields=["storage_key"], name="uk_documents_storage_key"),
            models.CheckConstraint(
                condition=models.Q(byte_size__gt=0), name="ck_documents_byte_size"
            ),
            models.CheckConstraint(
                condition=models.Q(sha256__isnull=True)
                | models.Q(sha256__regex=r"^[0-9a-f]{64}$"),
                name="ck_documents_sha256",
            ),
        ]
        indexes = [
            models.Index(fields=["uploaded_by"], name="idx_documents_uploaded_by"),
        ]

    def __str__(self) -> str:
        return self.original_filename


class NumberSeries(models.Model):
    """Business-facing counters, one row per prefix.

    The primary key is the prefix itself — there is no surrogate key, because
    the prefix *is* the identity. ``core.next_number()`` increments ``current``
    under a row lock; application code never writes this table directly.

    D6: the year lives in the prefix (``JOB-2026-``), so the counter resets
    naturally when the year rolls over — a new prefix is a new row.
    """

    prefix = models.TextField(primary_key=True)
    current = models.BigIntegerField(db_default=0, default=0)
    updated_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "core_number_series"
        default_permissions = ()
        verbose_name = "number series"
        verbose_name_plural = "number series"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(current__gte=0), name="ck_number_series_current"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.prefix} @ {self.current}"


class AuditOperation(models.TextChoices):
    INSERT = "INSERT", "Insert"
    UPDATE = "UPDATE", "Update"
    DELETE = "DELETE", "Delete"


class AuditLog(models.Model):
    """Append-only change history, range-partitioned on ``occurred_at``.

    ``managed = False`` (deviation 3.9). Django supports neither range
    partitioning nor the composite ``(id, occurred_at)`` primary key, so this
    model produces no DDL at all — the table, its partitions and the seven
    ``record_audit()`` triggers are created by
    ``core/migrations/0003_database_objects.py``.

    The model exists so the admin and selectors can *read* the log. Nothing
    writes to it from Python; the triggers do that, which is what makes the
    trail unbypassable — including from ``psql``.
    """

    # Django needs a single-column PK to build querysets. The real PK is
    # (id, occurred_at); reads are unaffected.
    id = models.BigIntegerField(primary_key=True)
    occurred_at = models.DateTimeField()
    table_schema = models.TextField()
    table_name = models.TextField()
    record_id = models.UUIDField(null=True)
    operation = models.TextField(choices=AuditOperation.choices)
    changed_by = models.UUIDField(null=True)
    old_data = models.JSONField(null=True)
    new_data = models.JSONField(null=True)

    class Meta:
        managed = False
        db_table = "core_audit_logs"
        default_permissions = ()
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"
        ordering = ["-occurred_at", "-id"]

    def __str__(self) -> str:
        return (
            f"{self.operation} {self.table_name} {self.record_id} "
            f"@ {self.occurred_at:%Y-%m-%d %H:%M}"
        )


__all__ = [
    "AuditLog",
    "AuditOperation",
    "Department",
    "Designation",
    "Document",
    "NumberSeries",
    "SoftDelete",
    "TimeStamped",
    "fk",
    "uuid",
]
