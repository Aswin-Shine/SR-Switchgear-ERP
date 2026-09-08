"""Document handling.

The schema is emphatic that ``core_documents`` holds *metadata*: the bytes live
in object storage and ``storage_key`` addresses them. This module is the only
place that writes both, and it writes them in that order — bytes first, row
second — so a crash leaves an orphaned object in the bucket rather than a row
pointing at nothing. An orphan costs storage; a dangling reference breaks every
page that renders the document.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.urls import reverse
from django.utils.text import get_valid_filename

from apps.core.db import audit_actor
from apps.core.exceptions import RuleViolation
from apps.core.models import Document
from apps.identity import constants
from apps.identity.services import require_permission

CHUNK = 64 * 1024


def _sha256_of(upload: UploadedFile) -> str:
    digest = hashlib.sha256()
    for chunk in upload.chunks(CHUNK):
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def _safe_key(original_filename: str) -> str:
    """A storage key the uploader cannot steer.

    The filename is attacker-controlled: ``../../etc/passwd`` or a 4KB name are
    both plausible. Only the extension is carried over, and even that is
    length-capped; the identity of the object is a fresh UUID.
    """
    suffix = PurePosixPath(original_filename or "").suffix[:16]
    if not suffix.isascii() or any(c in suffix for c in "/\\"):
        suffix = ""
    return f"documents/{uuid.uuid4()}{suffix}"


def upload_document(actor, upload: UploadedFile) -> Document:
    """Store the bytes and record the metadata."""
    require_permission(actor, constants.RES_DOCUMENT, "create")

    if upload is None:
        raise RuleViolation("No file was supplied.")
    if upload.size is None or upload.size <= 0:
        # ck_documents_byte_size would reject it anyway; failing here says why.
        raise RuleViolation("An empty file cannot be stored.")
    if upload.size > settings.MAX_UPLOAD_BYTES:
        raise RuleViolation(
            f"That file is {upload.size} bytes; the limit is "
            f"{settings.MAX_UPLOAD_BYTES}.",
            byte_size=upload.size,
            limit=settings.MAX_UPLOAD_BYTES,
        )

    sha256 = _sha256_of(upload)
    storage_key = _safe_key(upload.name)

    # Bytes first. See the module docstring.
    stored_key = default_storage.save(storage_key, upload)

    with audit_actor(actor):
        return Document.objects.create(
            storage_key=stored_key,
            original_filename=(upload.name or "unnamed")[:255],
            mime_type=upload.content_type or "application/octet-stream",
            byte_size=upload.size,
            sha256=sha256,
            uploaded_by=actor,
        )


def document_url(
    document: Document, *, download_name: str | None = None, expires: int = 900
) -> str:
    """A URL the browser can fetch the bytes from.

    On S3/MinIO this is a time-limited signed URL, which is why quotation PDFs
    are served as a 302 to storage rather than proxied through gunicorn: a
    worker tied up streaming a 4MB PDF is a worker not serving requests.

    ``download_name``, when given, is what the browser shows as the
    filename/tab title — the storage key itself stays an opaque UUID (see
    ``_safe_key``) regardless, so a caller with real business context (a
    quotation number and client name, say) can hand it over instead of
    leaving the user staring at a meaningless UUID.pdf with no way to tell
    which client it's for.
    """
    if download_name:
        safe_name = get_valid_filename(download_name)
        if settings.STORAGE_BACKEND == "s3":
            # Signed into the presigned URL itself — S3 serves the friendly
            # name directly, no bytes touch this process either way.
            return default_storage.url(
                document.storage_key,
                expire=expires,
                parameters={"ResponseContentDisposition": f'inline; filename="{safe_name}"'},
            )
        # FileSystemStorage has no per-request header hook, so the friendly
        # name is served through a small dedicated view instead of the raw
        # /media/<key> path django.views.static.serve exposes (config/urls.py)
        # — same trust model (the URL is the delivery mechanism, not a new
        # authorisation boundary), just a Content-Disposition worth reading.
        return reverse(
            "document-download", kwargs={"document_id": document.id, "filename": safe_name}
        )

    # S3Storage.url() takes an expiry; FileSystemStorage.url() does not and
    # raises TypeError if handed one. Development runs on the filesystem
    # backend, so this has to work on both.
    try:
        return default_storage.url(document.storage_key, expire=expires)
    except TypeError:
        return default_storage.url(document.storage_key)


def soft_delete_document(actor, document: Document) -> None:
    """Mark the metadata deleted. The bytes are deliberately left in place.

    Retention and erasure of the object itself is a storage-lifecycle question
    (and, for identity documents, a data-protection one — D9), not something to
    settle by deleting from under a row that other tables still reference with
    ON DELETE RESTRICT.
    """
    from django.utils import timezone

    require_permission(actor, constants.RES_DOCUMENT, "create", obj=document)
    with audit_actor(actor):
        document.deleted_at = timezone.now()
        document.save(update_fields=["deleted_at"])
