"""sales — clients, job cards, job lines, quotations.

Tables: sales_clients, sales_client_contacts, sales_product_categories,
sales_job_cards, sales_job_lines, sales_quotations, sales_quotation_lines,
sales_job_notes, sales_job_attachments.

The central modelling decision, confirmed with the business: a single enquiry
for 3 ATS panels + 2 AMF panels is **one job card and two job lines**, and the
job line — not the card — is what travels the pipeline. The card has no
``current_stage_id`` at all.
"""

from __future__ import annotations

from django.db import models

from apps.core.fields import CITextField, FixedCharField, Now, uuid_pk_kwargs
from apps.core.models import SoftDelete, TimeStamped, fk


class DispatchPolicy(models.TextChoices):
    """May this client's orders ship in parts?

    Lives on the client as a default and on the job card as the operative
    value. The convergence gate that reads it — "when a card is complete_only,
    no line may enter Dispatch until every sibling is ready" — belongs to the
    dispatch module and is deliberately not built (BACKEND_PLAN.md section 11).
    """

    PARTIAL_ALLOWED = "partial_allowed", "Partial dispatch allowed"
    COMPLETE_ONLY = "complete_only", "Complete order only"


class JobLifecycleStatus(models.TextChoices):
    """Pinned by ``ck_job_cards_lifecycle``. The commercial state of the card,
    distinct from where its lines sit in the pipeline."""

    OPEN = "open", "Open"
    QUOTED = "quoted", "Quoted"
    REWORK = "rework", "Rework"
    WON = "won", "Won"
    LOST = "lost", "Lost"
    CANCELLED = "cancelled", "Cancelled"


class EnquirySource(models.TextChoices):
    INDIAMART = "indiamart", "IndiaMART"
    WEBSITE = "website", "Website"
    PHONE = "phone", "Phone"
    REFERRAL = "referral", "Referral"
    WALK_IN = "walk_in", "Walk-in"
    OTHER = "other", "Other"


class JobLineStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ON_HOLD = "on_hold", "On hold"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class QuotationStatus(models.TextChoices):
    """Pinned by ``ck_quotations_status``.

    Two values only: a revision is either ``draft`` (the current one — the
    only one whose lines ``set_quotation_lines`` may still edit) or
    ``superseded`` (a later revision replaced it). There is no
    activate/send/accept workflow — the D7 status machine this repo
    originally shipped was removed once the real process turned out not to
    need it: a revision's PDF is uploaded and is immediately the thing Sales
    downloads and sends to the client themselves, outside this system.
    """

    DRAFT = "draft", "Draft"
    SUPERSEDED = "superseded", "Superseded"


class Client(TimeStamped, SoftDelete):
    id = models.UUIDField(**uuid_pk_kwargs())
    client_code = CITextField()
    legal_name = models.TextField()
    gstin = FixedCharField(max_length=15, null=True, blank=True)
    billing_city = models.TextField(null=True, blank=True)
    billing_state = models.TextField(null=True, blank=True)
    default_dispatch_policy = models.TextField(
        choices=DispatchPolicy.choices,
        db_default=DispatchPolicy.PARTIAL_ALLOWED,
        default=DispatchPolicy.PARTIAL_ALLOWED,
        help_text="Copied onto each new job card at creation. Changing it later "
                  "does not touch existing cards.",
    )
    is_active = models.BooleanField(db_default=True, default=True)
    created_by = fk(
        "identity.UserAccount", models.SET_NULL, null=True, blank=True,
        db_column="created_by", related_name="clients_created",
    )

    class Meta:
        db_table = "sales_clients"
        default_permissions = ()
        verbose_name = "client"
        constraints = [
            models.UniqueConstraint(fields=["client_code"], name="uk_clients_code"),
            models.UniqueConstraint(fields=["gstin"], name="uk_clients_gstin"),
            models.CheckConstraint(
                condition=models.Q(default_dispatch_policy__in=DispatchPolicy.values),
                name="ck_clients_dispatch",
            ),
            models.CheckConstraint(
                condition=models.Q(gstin__isnull=True)
                | models.Q(gstin__regex=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$"),
                name="ck_clients_gstin",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.client_code} — {self.legal_name}"


class ClientContact(TimeStamped, SoftDelete):
    id = models.UUIDField(**uuid_pk_kwargs())
    client = fk("sales.Client", models.CASCADE, related_name="contacts")
    contact_name = models.TextField()
    phone = models.TextField(null=True, blank=True)
    email = CITextField(null=True, blank=True)
    is_primary = models.BooleanField(db_default=False, default=False)

    class Meta:
        db_table = "sales_client_contacts"
        default_permissions = ()
        verbose_name = "client contact"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(phone__isnull=False) | models.Q(email__isnull=False),
                name="ck_client_contacts_reach",
            ),
            # One primary contact per client, ignoring soft-deleted rows.
            models.UniqueConstraint(
                fields=["client"],
                condition=models.Q(is_primary=True) & models.Q(deleted_at__isnull=True),
                name="uk_client_contacts_primary",
            ),
        ]
        indexes = [
            models.Index(fields=["client"], name="idx_client_contacts_client"),
        ]

    def __str__(self) -> str:
        return self.contact_name


class ProductCategory(TimeStamped):
    """Distinguishes manufactured panels from traded goods.

    ``is_manufactured = FALSE`` lets a job line take a different edge out of
    Quotation, skipping design and production — a data change, not a code
    change.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    code = CITextField()
    name = models.TextField()
    is_manufactured = models.BooleanField(db_default=True, default=True)
    is_active = models.BooleanField(db_default=True, default=True)

    class Meta:
        db_table = "sales_product_categories"
        default_permissions = ()
        verbose_name = "product category"
        verbose_name_plural = "product categories"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uk_product_categories_code"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class JobCard(TimeStamped, SoftDelete):
    """The commercial container — one client enquiry. Deliberately has no stage."""

    id = models.UUIDField(**uuid_pk_kwargs())
    job_no = models.TextField(help_text="Issued by core.next_number(). Never reused.")
    client = fk("sales.Client", models.PROTECT, related_name="job_cards")
    client_contact = fk(
        "sales.ClientContact", models.SET_NULL, null=True, blank=True,
        related_name="job_cards",
    )
    owner_user = fk(
        "identity.UserAccount", models.PROTECT, related_name="owned_job_cards",
        help_text="The sales rep. Attribution lives here, not inside job_no.",
    )
    lifecycle_status = models.TextField(
        choices=JobLifecycleStatus.choices,
        db_default=JobLifecycleStatus.OPEN,
        default=JobLifecycleStatus.OPEN,
    )
    enquiry_source = models.TextField(
        choices=EnquirySource.choices,
        db_default=EnquirySource.OTHER,
        default=EnquirySource.OTHER,
    )
    dispatch_policy = models.TextField(
        choices=DispatchPolicy.choices,
        db_default=DispatchPolicy.PARTIAL_ALLOWED,
        default=DispatchPolicy.PARTIAL_ALLOWED,
        help_text="Seeded from the client default at creation, overridable per "
                  "order, and change-tracked by the audit trigger on this table.",
    )
    # DEFAULT CURRENT_DATE in the schema — the database session's date. The
    # connection is pinned to Asia/Kolkata so a 00:30 IST enquiry is not dated
    # yesterday (see config.settings.base DATABASES TIME_ZONE).
    enquiry_date = models.DateField(db_default=models.functions.Now())
    required_by = models.DateField(null=True, blank=True)
    requirements = models.JSONField(db_default={}, default=dict, blank=True)

    class Meta:
        db_table = "sales_job_cards"
        default_permissions = ()
        verbose_name = "job card"
        constraints = [
            models.UniqueConstraint(fields=["job_no"], name="uk_job_cards_job_no"),
            models.CheckConstraint(
                condition=models.Q(lifecycle_status__in=JobLifecycleStatus.values),
                name="ck_job_cards_lifecycle",
            ),
            models.CheckConstraint(
                condition=models.Q(dispatch_policy__in=DispatchPolicy.values),
                name="ck_job_cards_dispatch",
            ),
            models.CheckConstraint(
                condition=models.Q(enquiry_source__in=EnquirySource.values),
                name="ck_job_cards_source",
            ),
            models.CheckConstraint(
                condition=models.Q(required_by__isnull=True)
                | models.Q(required_by__gte=models.F("enquiry_date")),
                name="ck_job_cards_required",
            ),
        ]
        indexes = [
            models.Index(fields=["client"], name="idx_job_cards_client"),
            models.Index(fields=["owner_user"], name="idx_job_cards_owner"),
            models.Index(
                fields=["owner_user", "-enquiry_date"],
                name="idx_job_cards_open",
                condition=models.Q(deleted_at__isnull=True)
                & models.Q(
                    lifecycle_status__in=[
                        JobLifecycleStatus.OPEN,
                        JobLifecycleStatus.QUOTED,
                        JobLifecycleStatus.REWORK,
                    ]
                ),
            ),
        ]

    def __str__(self) -> str:
        return self.job_no


class JobLine(TimeStamped, SoftDelete):
    """The unit that actually travels the pipeline."""

    id = models.UUIDField(**uuid_pk_kwargs())
    job_card = fk("sales.JobCard", models.CASCADE, related_name="lines")
    line_no = models.SmallIntegerField()
    product_category = fk("sales.ProductCategory", models.PROTECT, related_name="job_lines")
    description = models.TextField()
    quantity = models.IntegerField(db_default=1, default=1)
    current_stage = fk(
        "pipeline.Stage", models.PROTECT, related_name="job_lines",
        help_text="Denormalised cache of the latest transition. Written only by "
                  "the apply_transition() trigger — never assign it from Python.",
    )
    line_status = models.TextField(
        choices=JobLineStatus.choices,
        db_default=JobLineStatus.ACTIVE,
        default=JobLineStatus.ACTIVE,
    )
    required_by = models.DateField(null=True, blank=True)
    specs = models.JSONField(db_default={}, default=dict, blank=True)

    class Meta:
        db_table = "sales_job_lines"
        default_permissions = ()
        verbose_name = "job line"
        ordering = ["job_card", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_card", "line_no"], name="uk_job_lines_line_no"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="ck_job_lines_quantity"
            ),
            models.CheckConstraint(
                condition=models.Q(line_status__in=JobLineStatus.values),
                name="ck_job_lines_status",
            ),
        ]
        indexes = [
            models.Index(fields=["job_card"], name="idx_job_lines_job_card"),
            models.Index(fields=["product_category"], name="idx_job_lines_category"),
            models.Index(fields=["current_stage"], name="idx_job_lines_current_stage"),
        ]

    def __str__(self) -> str:
        return f"{self.job_card_id} line {self.line_no}"


class Quotation(TimeStamped):
    """Quotation header. The priced PDF is produced by external software;
    only the file and its commercial summary are stored.

    Revision model: a strictly linear chain. ``revision_no`` increments and
    ``supersedes`` points at the row this one replaces, with
    ``UNIQUE (supersedes_id)`` making branching impossible.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    quotation_no = models.TextField()
    job_card = fk("sales.JobCard", models.PROTECT, related_name="quotations")
    revision_no = models.SmallIntegerField(db_default=0, default=0)
    supersedes = fk(
        "self", models.PROTECT, null=True, blank=True, related_name="superseded_by",
    )
    status = models.TextField(
        choices=QuotationStatus.choices,
        db_default=QuotationStatus.DRAFT,
        default=QuotationStatus.DRAFT,
    )
    quoted_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    currency = FixedCharField(max_length=3, db_default="INR", default="INR")
    valid_till = models.DateField(null=True, blank=True)
    pdf_document = fk(
        "core.Document", models.PROTECT, null=True, blank=True, related_name="quotations"
    )
    prepared_by = fk(
        "identity.UserAccount", models.PROTECT,
        db_column="prepared_by", related_name="quotations_prepared",
    )

    class Meta:
        db_table = "sales_quotations"
        default_permissions = ()
        verbose_name = "quotation"
        ordering = ["job_card", "revision_no"]
        constraints = [
            models.UniqueConstraint(fields=["quotation_no"], name="uk_quotations_no"),
            models.UniqueConstraint(
                fields=["job_card", "revision_no"], name="uk_quotations_revision"
            ),
            models.UniqueConstraint(fields=["supersedes"], name="uk_quotations_supersedes"),
            models.CheckConstraint(
                condition=models.Q(status__in=QuotationStatus.values),
                name="ck_quotations_status",
            ),
            models.CheckConstraint(
                condition=models.Q(revision_no__gte=0), name="ck_quotations_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(quoted_amount__isnull=True)
                | models.Q(quoted_amount__gte=0),
                name="ck_quotations_amount",
            ),
        ]
        indexes = [
            models.Index(fields=["job_card"], name="idx_quotations_job_card"),
        ]

    def __str__(self) -> str:
        return f"{self.quotation_no} r{self.revision_no}"


class QuotationLine(models.Model):
    """Which job lines a given quotation revision actually priced.

    Deviation 3.8: this one keeps its composite primary key, carried by Django
    5.2's ``CompositePrimaryKey``. It is edited through services and is not
    registrable with the admin — which is fine, because nobody should be
    hand-editing priced lines in a generic CRUD form.
    """

    pk = models.CompositePrimaryKey("quotation_id", "job_line_id")
    quotation = fk("sales.Quotation", models.CASCADE, related_name="lines")
    job_line = fk("sales.JobLine", models.PROTECT, related_name="quotation_lines")
    line_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )

    class Meta:
        db_table = "sales_quotation_lines"
        default_permissions = ()
        verbose_name = "quotation line"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(line_amount__isnull=True) | models.Q(line_amount__gte=0),
                name="ck_quotation_lines_amt",
            ),
        ]
        indexes = [
            models.Index(fields=["job_line"], name="idx_quotation_lines_line"),
        ]

    def __str__(self) -> str:
        return f"{self.quotation_id} / {self.job_line_id}"


class JobNote(models.Model):
    """Free-text collaboration thread. Append-only: no updated_at, no soft delete."""

    id = models.UUIDField(**uuid_pk_kwargs())
    job_card = fk("sales.JobCard", models.CASCADE, related_name="notes")
    job_line = fk(
        "sales.JobLine", models.CASCADE, null=True, blank=True, related_name="notes"
    )
    author_user = fk("identity.UserAccount", models.PROTECT, related_name="job_notes")
    body = models.TextField()
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "sales_job_notes"
        default_permissions = ()
        verbose_name = "job note"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(body__regex=r"^\s*$"), name="ck_job_notes_body"
            ),
        ]
        indexes = [
            models.Index(fields=["job_card", "-created_at"], name="idx_job_notes_job_card"),
        ]

    def __str__(self) -> str:
        return f"note on {self.job_card_id}"


class JobAttachment(models.Model):
    """Any file attached to a job card — client drawings, site photos, POs."""

    id = models.UUIDField(**uuid_pk_kwargs())
    job_card = fk("sales.JobCard", models.CASCADE, related_name="attachments")
    job_line = fk(
        "sales.JobLine", models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    document = fk("core.Document", models.PROTECT, related_name="job_attachments")
    label = models.TextField(null=True, blank=True)
    attached_by = fk(
        "identity.UserAccount", models.PROTECT,
        db_column="attached_by", related_name="job_attachments",
    )
    attached_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "sales_job_attachments"
        default_permissions = ()
        verbose_name = "job attachment"
        ordering = ["-attached_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_card", "document"], name="uk_job_attachments"
            ),
        ]
        indexes = [
            models.Index(fields=["job_card"], name="idx_job_attachments_card"),
        ]

    def __str__(self) -> str:
        return self.label or str(self.document_id)
