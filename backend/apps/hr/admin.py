"""Admin for the employee master.

Appendix B's field tiers show up here concretely: the employee record is
readable and writable at ``perm_level`` 1, and personal identity documents at
level 2. A Sales user holds ``employee:view`` with ``if_owner`` at level 0, so
the list page is empty for them and their own record is reachable but not
editable.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import RBACModelAdmin
from apps.core.numbering import next_employee_code
from apps.hr.models import Employee, EmployeeDocument
from apps.identity import constants
from apps.identity.services import has_permission


@admin.register(Employee)
class EmployeeAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_EMPLOYEE
    rbac_view_level = constants.LEVEL_PROTECTED
    rbac_change_level = constants.LEVEL_PROTECTED

    list_display = ("employee_code", "full_name", "department", "designation",
                    "employment_status", "date_of_joining", "deleted_at")
    list_filter = ("employment_status", "department", "designation")
    search_fields = ("employee_code", "full_name", "personal_email")
    ordering = ("employee_code",)
    autocomplete_fields = ("department", "designation", "reports_to", "photo_document")
    # employee_code is never hand-entered here — see save_model below and
    # apps.hr.services's module docstring for the whole story.
    readonly_fields = ("employee_code", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.employee_code = next_employee_code()
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        """Soft-deleted employees stay visible to whoever can see the list.

        Hiding them would make an FK to a deleted employee look like data
        corruption. The filter is explicit and belongs to callers, not to a
        manager (BACKEND_PLAN.md section 4).
        """
        return super().get_queryset(request).select_related("department", "designation")


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(RBACModelAdmin):
    """Gated at level 2 — this is where Aadhaar and PAN scans would live.

    Whether such scans should be stored at all is still an open question for
    the business (D9). The access tier is in place either way, so the answer
    can change without a code change.
    """

    rbac_resource = constants.RES_EMPLOYEE_DOCUMENT
    rbac_view_level = constants.LEVEL_SENSITIVE
    rbac_change_level = constants.LEVEL_SENSITIVE

    list_display = ("employee", "doc_type", "is_sensitive", "created_at")
    list_filter = ("doc_type", "is_sensitive")
    search_fields = ("employee__employee_code", "employee__full_name")
    ordering = ("-created_at",)
    autocomplete_fields = ("employee", "document")

    def get_queryset(self, request):
        """Non-sensitive rows are visible at the ordinary level; sensitive rows
        need level 2. Filtering the queryset rather than the page keeps a
        level-0 holder from learning that a sensitive document exists."""
        qs = super().get_queryset(request).select_related("employee", "document")
        if has_permission(
            request.user,
            constants.RES_EMPLOYEE_DOCUMENT,
            "view",
            level=constants.LEVEL_SENSITIVE,
        ):
            return qs
        return qs.filter(is_sensitive=False)
