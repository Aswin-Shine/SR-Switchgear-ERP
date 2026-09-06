"""Contract tests for the session and reference endpoints.

Without DRF there is no schema to generate and no serializer to inspect, so
the response shape is only as stable as the tests that pin it. These assert the
*exact* key set, not a subset: adding a field to a payload should be a
deliberate act that updates a test, because the SPA is written against these
keys and a silent rename breaks it at runtime rather than at build time.
"""

import json

import pytest
from django.urls import reverse

from apps.identity import constants
from apps.identity.models import Role
from tests.factories import (
    ProductCategoryFactory,
    StageFactory,
    UserAccountFactory,
    UserRoleFactory,
)

PASSWORD = "a-perfectly-good-password"


@pytest.fixture
def owner(db):
    user = UserAccountFactory(password=PASSWORD)
    UserRoleFactory(user=user, role=Role.objects.get(code=constants.ROLE_OWNER))
    return user


@pytest.fixture
def signed_in(client, owner):
    client.force_login(owner)
    return client


def body(response):
    return json.loads(response.content)


# --- authentication gate ------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    ["/api/v1/me", "/api/v1/enums", "/api/v1/pipeline/stages", "/api/v1/product-categories"],
)
def test_endpoints_require_a_session(client, url):
    """401 with a JSON body, not a 302 to an HTML login page: the caller is an
    XHR and cannot read a redirect."""
    response = client.get(url)

    assert response.status_code == 401
    assert response["Content-Type"] == "application/json"
    assert body(response)["error"]["code"] == "authentication_required"


@pytest.mark.django_db
def test_wrong_method_returns_405_with_an_allow_header(signed_in):
    response = signed_in.post("/api/v1/enums")

    assert response.status_code == 405
    assert "GET" in response["Allow"]
    assert body(response)["error"]["code"] == "method_not_allowed"


# --- /me ----------------------------------------------------------------------


@pytest.mark.django_db
def test_me_payload_keys_are_exactly_this(signed_in):
    payload = body(signed_in.get("/api/v1/me"))

    assert set(payload) == {
        "id",
        "username",
        "full_name",
        "employee_id",
        "employee_code",
        "department",
        "must_change_password",
        "last_login",
        "roles",
        "grants",
    }


@pytest.mark.django_db
def test_me_returns_resolved_grants_not_role_names(signed_in, owner):
    payload = body(signed_in.get("/api/v1/me"))

    assert payload["grants"], "an Owner should hold grants"
    assert set(payload["grants"][0]) == {"resource", "action", "level", "if_owner"}

    pairs = {(g["resource"], g["action"]) for g in payload["grants"]}
    assert (constants.RES_QUOTATION, "create") in pairs
    assert (constants.RES_USER_ACCOUNT, "create") in pairs


@pytest.mark.django_db
def test_me_grants_match_what_the_engine_resolves(signed_in, owner):
    """The endpoint must not become a second, drifting implementation of the
    permission grid."""
    from apps.identity.services import resolve_permissions

    payload = body(signed_in.get("/api/v1/me"))
    from_api = {
        (g["resource"], g["action"], g["level"], g["if_owner"]) for g in payload["grants"]
    }
    from_engine = {
        (g.resource, g.action, g.perm_level, g.if_owner)
        for g in resolve_permissions(owner)
    }

    assert from_api == from_engine


@pytest.mark.django_db
def test_a_salesperson_sees_a_narrower_grant_set(client):
    salesperson = UserAccountFactory(password=PASSWORD)
    UserRoleFactory(user=salesperson, role=Role.objects.get(code=constants.ROLE_SALES))
    client.force_login(salesperson)

    pairs = {
        (g["resource"], g["action"]) for g in body(client.get("/api/v1/me"))["grants"]
    }

    assert (constants.RES_JOB_CARD, "create") in pairs
    assert (constants.RES_QUOTATION, "create") not in pairs
    assert (constants.RES_USER_ACCOUNT, "create") not in pairs


# --- /enums --------------------------------------------------------------------


@pytest.mark.django_db
def test_enums_payload_keys_are_exactly_this(signed_in):
    payload = body(signed_in.get("/api/v1/enums"))

    assert set(payload) == {
        "employment_status",
        "employee_document_type",
        "permission_action",
        "dispatch_policy",
        "job_lifecycle_status",
        "enquiry_source",
        "job_line_status",
        "quotation_status",
        "audit_operation",
    }
    for values in payload.values():
        assert values
        assert set(values[0]) == {"value", "label"}


@pytest.mark.django_db
def test_enum_values_match_the_database_check_constraints(signed_in, db_cursor):
    """The endpoint's job is to stop the SPA from inventing a status. If it
    ever disagrees with the CHECK, the SPA offers a value the database
    refuses."""
    payload = body(signed_in.get("/api/v1/enums"))

    db_cursor.execute(
        """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conname = 'ck_job_cards_lifecycle'
        """
    )
    definition = db_cursor.fetchone()[0]

    for entry in payload["job_lifecycle_status"]:
        assert f"'{entry['value']}'" in definition, entry


@pytest.mark.django_db
def test_dispatch_policy_offers_exactly_the_two_documented_values(signed_in):
    payload = body(signed_in.get("/api/v1/enums"))
    assert {e["value"] for e in payload["dispatch_policy"]} == {
        "partial_allowed",
        "complete_only",
    }


# --- /pipeline/stages -----------------------------------------------------------


@pytest.mark.django_db
def test_stages_payload_shape(signed_in):
    StageFactory(code="CONTRACTSTAGE", sequence_no=7010)

    payload = body(signed_in.get("/api/v1/pipeline/stages"))

    assert set(payload) == {"module_code", "items"}
    assert set(payload["items"][0]) == {
        "id",
        "code",
        "name",
        "module_code",
        "sequence_no",
        "department",
        "is_initial",
        "is_terminal",
    }


@pytest.mark.django_db
def test_stages_come_back_in_sequence_order(signed_in):
    StageFactory(code="LATESTAGE", sequence_no=7900)
    StageFactory(code="EARLYSTAGE", sequence_no=7100)

    items = body(signed_in.get("/api/v1/pipeline/stages"))["items"]
    sequences = [item["sequence_no"] for item in items]

    assert sequences == sorted(sequences)


@pytest.mark.django_db
def test_inactive_stages_are_omitted(signed_in):
    StageFactory(code="RETIREDSTAGE", sequence_no=7200, is_active=False)

    codes = {i["code"] for i in body(signed_in.get("/api/v1/pipeline/stages"))["items"]}

    assert "RETIREDSTAGE" not in codes


# --- /product-categories ---------------------------------------------------------


@pytest.mark.django_db
def test_product_categories_payload_shape(signed_in):
    ProductCategoryFactory(code="CONTRACTCAT", name="Contract category")

    payload = body(signed_in.get("/api/v1/product-categories"))

    assert set(payload) == {"items"}
    assert set(payload["items"][0]) == {"id", "code", "name", "is_manufactured"}


@pytest.mark.django_db
def test_is_manufactured_is_carried_through(signed_in):
    """Defect #2 in the schema review: traded goods were forced through design
    and production. The flag has to reach the client for that to be fixable."""
    ProductCategoryFactory(code="TRADED", name="Traded goods", is_manufactured=False)

    items = body(signed_in.get("/api/v1/product-categories"))["items"]
    traded = next(i for i in items if i["code"] == "TRADED")

    assert traded["is_manufactured"] is False


# --- password change over the API -------------------------------------------------


@pytest.mark.django_db
def test_change_password_endpoint(signed_in, owner):
    response = signed_in.post(
        "/api/v1/me/password",
        data=json.dumps(
            {"old_password": PASSWORD, "new_password": "an-entirely-different-secret"}
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    owner.refresh_from_db()
    assert owner.check_password("an-entirely-different-secret")


@pytest.mark.django_db
def test_change_password_with_a_bad_current_password_is_403(signed_in):
    response = signed_in.post(
        "/api/v1/me/password",
        data=json.dumps({"old_password": "wrong", "new_password": "a-new-long-secret"}),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert body(response)["error"]["code"] == "permission_denied"


@pytest.mark.django_db
def test_a_weak_new_password_is_422(signed_in):
    response = signed_in.post(
        "/api/v1/me/password",
        data=json.dumps({"old_password": PASSWORD, "new_password": "short"}),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert body(response)["error"]["code"] == "rule_violation"


@pytest.mark.django_db
def test_missing_fields_are_422_and_name_what_is_missing(signed_in):
    response = signed_in.post(
        "/api/v1/me/password",
        data=json.dumps({"old_password": PASSWORD}),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert body(response)["error"]["context"]["missing"] == ["new_password"]


@pytest.mark.django_db
def test_malformed_json_is_422_not_500(signed_in):
    response = signed_in.post(
        "/api/v1/me/password", data="{not json", content_type="application/json"
    )

    assert response.status_code == 422


# --- server-rendered pages ---------------------------------------------------------


@pytest.mark.django_db
def test_login_page_renders_anonymously(client):
    assert client.get(reverse("login")).status_code == 200


@pytest.mark.django_db
def test_must_change_password_forces_the_rotation_page(client):
    user = UserAccountFactory(password=PASSWORD, must_change_password=True)
    client.force_login(user)

    response = client.get("/app/")

    assert response.status_code == 302
    assert response["Location"] == reverse("password-change")


@pytest.mark.django_db
def test_the_spa_shell_embeds_a_csrf_token(signed_in):
    """CSRF_COOKIE_HTTPONLY stays True only because the token is readable from
    the document instead of from a cookie."""
    response = signed_in.get("/app/")

    assert response.status_code == 200
    assert b'name="csrf-token"' in response.content


@pytest.mark.django_db
def test_healthz_is_open_and_checks_the_database(client):
    response = client.get("/healthz/")

    assert response.status_code == 200
    assert body(response) == {"status": "ok", "database": "ok"}
