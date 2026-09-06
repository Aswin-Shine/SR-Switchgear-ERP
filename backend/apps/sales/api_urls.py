from django.urls import path

from apps.sales import api

urlpatterns = [
    path("dashboard", api.dashboard, name="dashboard"),
    path("product-categories", api.product_categories, name="product-categories"),

    path("clients", api.clients, name="clients"),
    path("clients/<uuid:client_id>", api.client_detail, name="client-detail"),
    path("clients/<uuid:client_id>/contacts", api.client_contacts, name="client-contacts"),

    path("job-cards", api.job_cards, name="job-cards"),
    path("job-cards/<uuid:card_id>", api.job_card_detail, name="job-card-detail"),
    path("job-cards/<uuid:card_id>/cancel", api.cancel_job_card, name="job-card-cancel"),
    path("job-cards/<uuid:card_id>/lines", api.job_card_lines, name="job-card-lines"),
    path("job-cards/<uuid:card_id>/notes", api.job_card_notes, name="job-card-notes"),
    path(
        "job-cards/<uuid:card_id>/attachments",
        api.job_card_attachments,
        name="job-card-attachments",
    ),
    path(
        "job-cards/<uuid:card_id>/attachments/<uuid:attachment_id>",
        api.job_card_attachment_detail,
        name="job-card-attachment-detail",
    ),
    path(
        "attachments/<uuid:attachment_id>/download",
        api.attachment_download,
        name="attachment-download",
    ),
    path(
        "job-cards/<uuid:card_id>/quotations",
        api.job_card_quotations,
        name="job-card-quotations",
    ),

    path("job-lines/<uuid:line_id>/edit", api.job_line_update, name="job-line-update"),

    path("quotations/<uuid:quotation_id>", api.quotation_detail, name="quotation-detail"),
    path("quotations/<uuid:quotation_id>/pdf", api.quotation_pdf, name="quotation-pdf"),
]
