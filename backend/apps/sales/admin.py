"""Admin for the sales module.

``QuotationLine`` is deliberately absent: it carries a composite primary key,
which ``AdminSite.register`` refuses outright (deviation 3.8), and priced lines
should not be hand-edited in a generic CRUD form anyway. They are written
through ``sales.services``.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import RBACModelAdmin, ReadOnlyAdmin
from apps.core.numbering import next_client_code
from apps.identity import constants
from apps.sales.models import (
    Client,
    ClientContact,
    JobAttachment,
    JobCard,
    JobLine,
    JobNote,
    ProductCategory,
    Quotation,
)


class ClientContactInline(admin.TabularInline):
    model = ClientContact
    extra = 0
    fields = ("contact_name", "phone", "email", "is_primary", "deleted_at")


@admin.register(Client)
class ClientAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_CLIENT
    list_display = ("client_code", "legal_name", "gstin", "billing_city",
                    "default_dispatch_policy", "is_active")
    list_filter = ("is_active", "default_dispatch_policy", "billing_state")
    search_fields = ("client_code", "legal_name", "gstin")
    ordering = ("client_code",)
    inlines = [ClientContactInline]
    # client_code is never hand-entered here — see save_model below and
    # apps.sales.services.create_client for the whole story.
    readonly_fields = ("client_code", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.client_code = next_client_code()
        super().save_model(request, obj, form, change)


@admin.register(ClientContact)
class ClientContactAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_CLIENT
    list_display = ("contact_name", "client", "phone", "email", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("contact_name", "client__legal_name", "email")
    autocomplete_fields = ("client",)


@admin.register(ProductCategory)
class ProductCategoryAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_JOB_LINE
    list_display = ("code", "name", "is_manufactured", "is_active")
    list_filter = ("is_manufactured", "is_active")
    search_fields = ("code", "name")
    ordering = ("code",)


class JobLineInline(admin.TabularInline):
    model = JobLine
    extra = 0
    fields = ("line_no", "product_category", "description", "quantity",
              "current_stage", "line_status", "required_by")
    # current_stage is maintained by the apply_transition() trigger. Offering
    # it as an editable field here would invite exactly the desynchronisation
    # the trigger exists to prevent.
    readonly_fields = ("current_stage",)
    autocomplete_fields = ("product_category",)


@admin.register(JobCard)
class JobCardAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_JOB_CARD
    list_display = ("job_no", "client", "owner_user", "lifecycle_status",
                    "dispatch_policy", "enquiry_date", "required_by")
    list_filter = ("lifecycle_status", "dispatch_policy", "enquiry_source")
    search_fields = ("job_no", "client__legal_name", "client__client_code")
    date_hierarchy = "enquiry_date"
    ordering = ("-enquiry_date",)
    autocomplete_fields = ("client", "client_contact", "owner_user")
    inlines = [JobLineInline]
    readonly_fields = ("job_no", "created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("client", "owner_user")


@admin.register(JobLine)
class JobLineAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_JOB_LINE
    list_display = ("job_card", "line_no", "product_category", "description",
                    "quantity", "current_stage", "line_status")
    list_filter = ("line_status", "current_stage", "product_category")
    search_fields = ("job_card__job_no", "description")
    ordering = ("job_card__job_no", "line_no")
    autocomplete_fields = ("job_card", "product_category")
    readonly_fields = ("current_stage", "created_at", "updated_at")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("job_card", "product_category", "current_stage")
        )


@admin.register(Quotation)
class QuotationAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_QUOTATION
    list_display = ("quotation_no", "job_card", "revision_no", "status",
                    "quoted_amount", "currency", "valid_till")
    list_filter = ("status", "currency")
    search_fields = ("quotation_no", "job_card__job_no")
    ordering = ("-created_at",)
    autocomplete_fields = ("job_card", "supersedes", "pdf_document", "prepared_by")
    readonly_fields = ("quotation_no", "revision_no", "supersedes",
                       "created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("job_card", "prepared_by")


@admin.register(JobNote)
class JobNoteAdmin(ReadOnlyAdmin):
    """Append-only, and a collaboration record. Editing somebody else's note
    after the fact would make the thread untrustworthy."""

    rbac_resource = constants.RES_JOB_NOTE
    list_display = ("job_card", "job_line", "author_user", "created_at")
    search_fields = ("job_card__job_no", "body")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(JobAttachment)
class JobAttachmentAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_JOB_CARD
    list_display = ("job_card", "job_line", "label", "document", "attached_by",
                    "attached_at")
    search_fields = ("job_card__job_no", "label")
    ordering = ("-attached_at",)
    autocomplete_fields = ("job_card", "job_line", "document", "attached_by")


ClientAdmin.search_fields = ("client_code", "legal_name", "gstin")
JobCardAdmin.search_fields = ("job_no", "client__legal_name", "client__client_code")
JobLineAdmin.search_fields = ("job_card__job_no", "description")
ProductCategoryAdmin.search_fields = ("code", "name")
