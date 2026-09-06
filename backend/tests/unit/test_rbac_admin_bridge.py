"""Deviation 3.11: making Django's admin ask our RBAC for permission.

The admin calls ``request.user.is_staff`` and
``request.user.has_perm("app_label.codename")``. ``AbstractBaseUser`` provides
neither and ``auth_user_accounts`` has no ``is_staff`` column, so both are
derived. These tests pin that derivation, because if it silently starts
answering False the admin becomes inaccessible to everyone, and if it silently
starts answering True it becomes accessible to everyone.
"""

import pytest

from apps.identity import constants
from apps.identity.models import Role
from apps.identity.services import (
    deactivate_user_account,
    has_any_permission,
    invalidate_permission_cache,
    is_owner,
    set_password_for,
)
from tests.factories import (
    ClientFactory,
    DocumentFactory,
    EmployeeDocumentFactory,
    JobCardFactory,
    JobLineFactory,
    JobNoteFactory,
    ProductCategoryFactory,
    QuotationFactory,
    StageFactory,
    UserAccountFactory,
    UserRoleFactory,
)


def with_role(code: str):
    user = UserAccountFactory()
    UserRoleFactory(user=user, role=Role.objects.get(code=code))
    return user


# --- is_staff ----------------------------------------------------------------


@pytest.mark.django_db
def test_is_staff_follows_the_admin_site_view_permission():
    owner = with_role(constants.ROLE_OWNER)
    salesperson = with_role(constants.ROLE_SALES)

    assert owner.is_staff is True
    assert salesperson.is_staff is False


@pytest.mark.django_db
def test_no_user_is_ever_a_superuser():
    """There is no is_superuser column and no code path that grants one."""
    assert with_role(constants.ROLE_OWNER).is_superuser is False


# --- has_perm ----------------------------------------------------------------


@pytest.mark.django_db
def test_django_codename_maps_onto_our_resources():
    owner = with_role(constants.ROLE_OWNER)

    assert owner.has_perm("hr.view_employee") is True
    assert owner.has_perm("sales.add_jobcard") is True
    assert owner.has_perm("sales.change_jobcard") is True


@pytest.mark.django_db
def test_django_codename_refuses_what_the_grid_refuses():
    accountant = with_role(constants.ROLE_ACCT)

    assert accountant.has_perm("sales.add_jobcard") is False
    assert accountant.has_perm("sales.view_jobcard") is True


@pytest.mark.django_db
def test_malformed_codenames_are_refused_rather_than_crashing():
    owner = with_role(constants.ROLE_OWNER)

    assert owner.has_perm("nonsense") is False
    assert owner.has_perm("hr.nodelimiter") is False
    assert owner.has_perm("hr.frobnicate_employee") is False


@pytest.mark.django_db
def test_has_perms_requires_all_of_them():
    owner = with_role(constants.ROLE_OWNER)
    accountant = with_role(constants.ROLE_ACCT)

    assert owner.has_perms(["hr.view_employee", "sales.view_jobcard"]) is True
    assert accountant.has_perms(["hr.view_employee", "sales.view_jobcard"]) is False


@pytest.mark.django_db
def test_owner_scoped_codename_permission_needs_the_object():
    salesperson = with_role(constants.ROLE_SALES)

    assert salesperson.has_perm("hr.view_employee") is False
    assert salesperson.has_perm("hr.view_employee", obj=salesperson.employee) is True


# --- has_module_perms --------------------------------------------------------


@pytest.mark.django_db
def test_module_perms_decide_which_apps_appear_in_the_admin_index():
    owner = with_role(constants.ROLE_OWNER)
    hr = with_role(constants.ROLE_HR)
    storekeeper = with_role(constants.ROLE_STORE)

    assert owner.has_module_perms("sales") is True
    assert owner.has_module_perms("pipeline") is True

    assert hr.has_module_perms("hr") is True
    assert hr.has_module_perms("pipeline") is False

    assert storekeeper.has_module_perms("sales") is True
    assert storekeeper.has_module_perms("hr") is True  # own record only


@pytest.mark.django_db
def test_unknown_app_label_is_refused():
    assert with_role(constants.ROLE_OWNER).has_module_perms("not_an_app") is False


# --- has_any_permission ------------------------------------------------------


@pytest.mark.django_db
def test_has_any_permission_ignores_scope():
    salesperson = with_role(constants.ROLE_SALES)

    # Granted, but only over their own record.
    assert has_any_permission(salesperson, constants.RES_EMPLOYEE, "view") is True
    assert has_any_permission(salesperson, constants.RES_EMPLOYEE, "edit") is False


# --- ownership rules ---------------------------------------------------------


@pytest.mark.django_db
def test_ownership_rules_cover_every_model_that_has_an_owner():
    user = UserAccountFactory()

    assert is_owner(user, user) is True
    assert is_owner(user, user.employee) is True
    assert is_owner(user, DocumentFactory(uploaded_by=user)) is True
    assert is_owner(user, ClientFactory(created_by=user)) is True
    assert is_owner(user, JobCardFactory(owner_user=user)) is True
    assert is_owner(user, QuotationFactory(prepared_by=user)) is True
    assert is_owner(user, JobNoteFactory(author_user=user)) is True
    assert is_owner(user, EmployeeDocumentFactory(employee=user.employee)) is True


@pytest.mark.django_db
def test_job_line_ownership_is_inherited_from_its_card():
    """A job line has no owner column; the card's sales rep owns it."""
    user = UserAccountFactory()
    stage = StageFactory(code="OWNTEST", sequence_no=4010)
    mine = JobLineFactory(
        job_card=JobCardFactory(owner_user=user),
        current_stage=stage,
        product_category=ProductCategoryFactory(code="OWNCAT"),
    )
    theirs = JobLineFactory(current_stage=stage, product_category=mine.product_category)

    assert is_owner(user, mine) is True
    assert is_owner(user, theirs) is False


@pytest.mark.django_db
def test_a_model_with_no_ownership_rule_is_never_owned():
    """Failing closed: an owner-scoped grant over a model with no notion of
    ownership can never be satisfied."""
    user = UserAccountFactory()
    assert is_owner(user, StageFactory(code="NOOWNER", sequence_no=4020)) is False
    assert is_owner(user, None) is False


# --- administrative account actions ------------------------------------------


@pytest.mark.django_db
def test_an_administrator_can_reset_someone_elses_password():
    admin = with_role(constants.ROLE_ADMIN)
    target = UserAccountFactory(password="their-old-password")

    set_password_for(admin, target, "a-fresh-administrative-secret")

    target.refresh_from_db()
    assert target.check_password("a-fresh-administrative-secret")
    # Forced rotation: the administrator knows this value.
    assert target.must_change_password is True


@pytest.mark.django_db
def test_resetting_a_password_still_runs_the_validators():
    from apps.core.exceptions import RuleViolation

    admin = with_role(constants.ROLE_ADMIN)
    target = UserAccountFactory()

    with pytest.raises(RuleViolation):
        set_password_for(admin, target, "short")


@pytest.mark.django_db
def test_a_salesperson_cannot_reset_anyone_elses_password():
    from apps.core.exceptions import PermissionDenied

    salesperson = with_role(constants.ROLE_SALES)
    target = UserAccountFactory(password="their-old-password")

    with pytest.raises(PermissionDenied):
        set_password_for(salesperson, target, "a-fresh-administrative-secret")

    target.refresh_from_db()
    assert target.check_password("their-old-password")


@pytest.mark.django_db
def test_deactivating_an_account_revokes_everything_it_held():
    admin = with_role(constants.ROLE_ADMIN)
    target = with_role(constants.ROLE_SALES)
    assert has_any_permission(target, constants.RES_JOB_CARD, "create") is True

    deactivate_user_account(admin, target)

    target.refresh_from_db()
    invalidate_permission_cache(target)
    assert target.is_active is False
    assert has_any_permission(target, constants.RES_JOB_CARD, "create") is False
