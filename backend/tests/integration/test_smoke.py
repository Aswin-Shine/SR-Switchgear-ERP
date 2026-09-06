"""Phase 0 smoke test: a real connection to a real PostgreSQL 16."""

import pytest
from django.db import connection


@pytest.mark.django_db
def test_database_is_postgresql_16():
    """The whole test strategy assumes PostgreSQL 16. Fail loudly if it is not."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]

    assert "PostgreSQL" in version, version
    major = connection.cursor().connection.info.server_version // 10000
    assert major >= 16, f"expected PostgreSQL 16 or newer, got {version}"


@pytest.mark.django_db
def test_citext_extension_is_available():
    """Nine columns are citext. Without the extension nothing migrates."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'citext'")
        assert cursor.fetchone() is not None, "citext extension is not installed"


@pytest.mark.django_db
def test_connection_timezone_is_ist():
    """sales_job_cards.enquiry_date defaults to CURRENT_DATE, which reads the
    session's timezone. If this drifts to UTC, enquiries logged after 18:30 UTC
    get the wrong date."""
    with connection.cursor() as cursor:
        cursor.execute("SHOW TimeZone")
        assert cursor.fetchone()[0] == "Asia/Kolkata"
