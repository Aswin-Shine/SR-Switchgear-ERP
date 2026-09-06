"""The RBAC-aware admin base, plus the core app's own registrations.

Deviation 3.11. Django's ``ModelAdmin`` asks four questions —
``has_view_permission``, ``has_add_permission``, ``has_change_permission``,
``has_delete_permission`` — and answers them by calling
``request.user.has_perm("app_label.codename")``. Left alone, that would route
authority through ``auth_permission``, a table this project deliberately leaves
empty. ``RBACModelAdmin`` re-routes all four into
``identity.services.has_permission`` so there is exactly one answer to "may
this person do this", whether the question comes from the SPA or the admin.
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.models import Group

from apps.core.models import AuditLog, Department, Designation, Document, NumberSeries
from apps.identity import constants
from apps.identity.services import has_permission

# Django's own Group model is registered by django.contrib.auth.admin and is
# unused here — roles live in auth_roles. Leaving it visible would invite
# someone to configure permissions in a table nothing reads.
try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:  # pragma: no cover — depends on app order
    pass

admin.site.site_header = "SR Switchgear ERP"
admin.site.site_title = "SR Switchgear ERP"
admin.site.index_title = "Administration"


class RBACModelAdmin(admin.ModelAdmin):
    """Routes the admin's four permission hooks into our RBAC.

    Subclasses set ``rbac_resource``. ``rbac_view_level`` and
    ``rbac_change_level`` express Appendix B's field tiers where a model needs
    them — ``employee`` is readable at level 1, employee documents at level 2.
    """

    rbac_resource: str = ""
    rbac_view_level: int = 0
    rbac_change_level: int = 0

    def _may(self, request, action: str, obj=None, level: int = 0) -> bool:
        if not self.rbac_resource:  # pragma: no cover — a subclass forgot to set it
            return False
        return has_permission(
            request.user, self.rbac_resource, action, obj=obj, level=level
        )

    def has_view_permission(self, request, obj=None) -> bool:
        return self._may(request, "view", obj=obj, level=self.rbac_view_level)

    def has_add_permission(self, request) -> bool:
        return self._may(request, "create")

    def has_change_permission(self, request, obj=None) -> bool:
        return self._may(request, "edit", obj=obj, level=self.rbac_change_level)

    def has_delete_permission(self, request, obj=None) -> bool:
        return self._may(request, "delete", obj=obj)

    def has_module_permission(self, request) -> bool:
        return self.has_view_permission(request)

    # Models built on (TimeStamped, SoftDelete) put `deleted_at` first in
    # _meta.fields (Django orders multiple abstract bases in MRO order, and
    # SoftDelete resolves before TimeStamped there), which otherwise puts a
    # soft-delete timestamp above every real field on the add/change form.
    _TRAILING_FIELDS = ("created_at", "updated_at", "deleted_at")

    # created_at/updated_at use db_default=Now() — Postgres fills them in on
    # INSERT, Django never computes them client-side. On an unsaved add-form
    # instance there's no row yet, so the readonly widget renders the
    # placeholder object standing in for "whatever the database will put
    # here" (`<django.db.models.expressions.DatabaseDefault object at ...>`)
    # instead of a date. Meaningless before save either way, so just don't
    # show them there; `deleted_at` stays — it's a plain default=None field,
    # not a db_default expression, so it renders fine (blank) on add.
    _DB_DEFAULT_TIMESTAMP_FIELDS = ("created_at", "updated_at")

    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        if obj is None:
            fields = [f for f in fields if f not in self._DB_DEFAULT_TIMESTAMP_FIELDS]
        trailing = [f for f in self._TRAILING_FIELDS if f in fields]
        if not trailing:
            return fields
        return [f for f in fields if f not in trailing] + trailing


class ReadOnlyAdmin(RBACModelAdmin):
    """For records that must never be edited through a generic CRUD form."""

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Department)
class DepartmentAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_EMPLOYEE
    rbac_view_level = constants.LEVEL_PROTECTED
    rbac_change_level = constants.LEVEL_PROTECTED
    list_display = ("code", "name", "parent_department", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    ordering = ("code",)


@admin.register(Designation)
class DesignationAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_EMPLOYEE
    rbac_view_level = constants.LEVEL_PROTECTED
    rbac_change_level = constants.LEVEL_PROTECTED
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    ordering = ("code",)


@admin.register(Document)
class DocumentAdmin(ReadOnlyAdmin):
    """Metadata only, and read-only: the bytes live in object storage, so
    editing a storage_key here would silently orphan a file."""

    rbac_resource = constants.RES_DOCUMENT
    list_display = ("original_filename", "mime_type", "byte_size", "uploaded_by",
                    "uploaded_at")
    list_filter = ("mime_type",)
    search_fields = ("original_filename", "storage_key", "sha256")
    ordering = ("-uploaded_at",)


@admin.register(NumberSeries)
class NumberSeriesAdmin(ReadOnlyAdmin):
    """Read-only on purpose. Editing ``current`` by hand would reissue a job
    number that is already on a document somewhere."""

    rbac_resource = constants.RES_AUDIT_LOG
    list_display = ("prefix", "current", "updated_at")
    ordering = ("prefix",)


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    """The trail. Read-only in the strongest sense available: the model is
    ``managed = False``, the table is written only by triggers, and all three
    mutating hooks are refused."""

    rbac_resource = constants.RES_AUDIT_LOG
    list_display = ("occurred_at", "table_name", "operation", "record_id", "changed_by")
    list_filter = ("operation", "table_name")
    search_fields = ("record_id", "changed_by")
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at",)
