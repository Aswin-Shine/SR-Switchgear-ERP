"""Contract tests for the /print/ server-rendered views."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.identity import constants
from apps.identity.models import Role
from apps.sales.services import (
    add_job_line,
    cancel_job_card,
    create_job_card,
    create_quotation_revision,
)
from tests.factories import (
    ClientFactory,
    ProductCategoryFactory,
    UserAccountFactory,
    UserRoleFactory,
)

PASSWORD = "a-perfectly-good-password"


def with_role(*codes: str):
    user = UserAccountFactory(password=PASSWORD)
    for code in codes:
        UserRoleFactory(user=user, role=Role.objects.get(code=code))
    return user


@pytest.fixture
def sales(db):
    return with_role(constants.ROLE_SALES)


@pytest.fixture
def owner(db):
    return with_role(constants.ROLE_OWNER)


@pytest.fixture
def accountant(db):
    return with_role(constants.ROLE_ACCT)


@pytest.fixture
def card(sales):
    return create_job_card(sales, ClientFactory())


def a_pdf(name="quote.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 quotation", content_type="application/pdf")


@pytest.mark.django_db
def test_an_anonymous_visitor_is_sent_to_login(client, card):
    response = client.get(f"/print/job-card/{card.job_no}")

    assert response.status_code == 302
    assert response["Location"].startswith("/login/")


@pytest.mark.django_db
def test_a_role_with_no_job_card_view_grant_gets_a_403_not_a_crash(client, card):
    """HR is the one role in the grid with no job_card:view at all."""
    client.force_login(with_role(constants.ROLE_HR))

    response = client.get(f"/print/job-card/{card.job_no}")

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_nonexistent_card_is_a_404(client, sales):
    client.force_login(sales)

    response = client.get("/print/job-card/JOB-1900-99999")

    assert response.status_code == 404


@pytest.mark.django_db
def test_the_page_shows_the_job_card_and_its_lines(client, sales, card):
    category = ProductCategoryFactory(code="PRINTVIEWCAT")
    add_job_line(sales, card, product_category=category, description="LT panel", quantity=3)
    client.force_login(sales)

    response = client.get(f"/print/job-card/{card.job_no}")

    assert response.status_code == 200
    body = response.content.decode()
    assert card.job_no in body
    assert card.client.legal_name in body
    assert "LT panel" in body
    assert "Current quotation" not in body


@pytest.mark.django_db
def test_the_page_shows_the_current_quotation_when_one_exists(client, sales, owner, card):
    add_job_line(
        sales, card, product_category=ProductCategoryFactory(code="PRINTVIEWQCAT"),
        description="Panel", quantity=1,
    )
    quotation = create_quotation_revision(owner, card, pdf=a_pdf())
    client.force_login(sales)

    response = client.get(f"/print/job-card/{card.job_no}")

    body = response.content.decode()
    assert "Current quotation" in body
    assert f"Rev {quotation.revision_no}" in body


@pytest.mark.django_db
def test_a_cancelled_card_carries_a_visible_warning_banner(client, sales, owner, card):
    cancel_job_card(owner, card, reason="Client withdrew the enquiry")
    client.force_login(sales)

    response = client.get(f"/print/job-card/{card.job_no}")

    body = response.content.decode()
    assert "do not proceed with production" in body
    assert "dead-banner" in body


@pytest.mark.django_db
def test_an_open_card_carries_no_warning_banner(client, sales, card):
    client.force_login(sales)

    response = client.get(f"/print/job-card/{card.job_no}")

    body = response.content.decode()
    assert "dead-banner" not in body
