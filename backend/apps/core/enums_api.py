"""``GET /api/v1/enums`` — the CHECK-constrained domains, served to the SPA.

These are the four (plus a few) status domains the database itself pins with a
CHECK constraint. The SPA needs them to render dropdowns, and shipping them
from here rather than hard-coding them in TypeScript means a domain can only
disagree with the database if someone edits the model and forgets the
migration — at which point the CHECK rejects the write anyway.

Stage codes and role codes are deliberately NOT here. Those are rows, not
domains, and they have their own endpoints.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse

from apps.core.api import api, ok
from apps.core.models import AuditOperation
from apps.hr.models import EmployeeDocumentType, EmploymentStatus
from apps.identity.models import PermissionAction
from apps.sales.models import (
    DispatchPolicy,
    EnquirySource,
    JobLifecycleStatus,
    JobLineStatus,
    QuotationStatus,
)

DOMAINS = {
    "employment_status": EmploymentStatus,
    "employee_document_type": EmployeeDocumentType,
    "permission_action": PermissionAction,
    "dispatch_policy": DispatchPolicy,
    "job_lifecycle_status": JobLifecycleStatus,
    "enquiry_source": EnquirySource,
    "job_line_status": JobLineStatus,
    "quotation_status": QuotationStatus,
    "audit_operation": AuditOperation,
}


@api(["GET"])
def enums(request: HttpRequest) -> JsonResponse:
    return ok(
        {
            name: [{"value": value, "label": label} for value, label in choices.choices]
            for name, choices in DOMAINS.items()
        }
    )
