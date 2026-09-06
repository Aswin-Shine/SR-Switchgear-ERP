"""The RBAC engine. This is where the bugs would be, so this is where the tests are."""

import pytest

from apps.core.exceptions import PermissionDenied, RuleViolation
from apps.identity import constants
from apps.identity.models import Permission, Role, RolePermission, UserAccount, UserRole
from apps.identity.services import (
    Grant,
    assign_role,
    change_own_password,
    create_user_account,
    has_permission,
    invalidate_permission_cache,
    owner_scope_for,
    resolve_permissions,
    revoke_role,
)
from tests.factories import (
    ClientFactory,
    EmployeeFactory,
    JobCardFactory,
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserAccountFactory,
    UserRoleFactory,
)


def grant(user, resource, action, *, level=0, if_owner=False, role=None):
    """Attach one capability to a user, creating the role if needed."""
    role = role or RoleFactory()
    permission = PermissionFactory(resource=resource, action=action)
    RolePermissionFactory(
        role=role, permission=permission, perm_level=level, if_owner=if_owner
    )
    UserRole.objects.get_or_create(user=user, role=role)
    invalidate_permission_cache(user)
    return role


# --- resolve_permissions ------------------------------------------------------


@pytest.mark.django_db
def test_union_across_two_roles():
    user = UserAccountFactory()
    grant(user, "client", "view")
    grant(user, "quotation", "approve")

    resolved = resolve_permissions(user)

    assert Grant("client", "view", 0, False) in resolved
    assert Grant("quotation", "approve", 0, False) in resolved


@pytest.mark.django_db
def test_highest_perm_level_wins_for_the_same_pair():
    user = UserAccountFactory()
    permission = PermissionFactory(resource="employee", action="view")

    for level in (0, 1):
        role = RoleFactory()
        RolePermissionFactory(role=role, permission=permission, perm_level=level)
        UserRoleFactory(user=user, role=role)
    invalidate_permission_cache(user)

    matching = [g for g in resolve_permissions(user) if g.resource == "employee"]
    assert len(matching) == 1
    assert matching[0].perm_level == 1


@pytest.mark.django_db
def test_if_owner_is_dropped_when_an_unrestricted_grant_covers_it():
    """A user who is both HR and Sales sees every employee, not only themselves."""
    user = UserAccountFactory()
    permission = PermissionFactory(resource="employee", action="view")

    hr_role = RoleFactory(code="HRISH")
    RolePermissionFactory(role=hr_role, permission=permission, perm_level=1, if_owner=False)
    sales_role = RoleFactory(code="SALESISH")
    RolePermissionFactory(role=sales_role, permission=permission, perm_level=0, if_owner=True)
    UserRoleFactory(user=user, role=hr_role)
    UserRoleFactory(user=user, role=sales_role)
    invalidate_permission_cache(user)

    matching = [g for g in resolve_permissions(user) if g.resource == "employee"]
    assert len(matching) == 1
    assert matching[0] == Grant("employee", "view", 1, False)


@pytest.mark.django_db
def test_owner_scoped_grant_survives_when_it_outranks_the_unrestricted_one():
    """The escalation this design refuses to allow.

    A level-2 grant restricted to one's own records, plus a level-0
    unrestricted grant, must NOT collapse into level-2 unrestricted — that
    would hand every employee's sensitive documents to the holder of a level-0
    grant.
    """
    user = UserAccountFactory()
    permission = PermissionFactory(resource="employee_document", action="view")

    low = RoleFactory(code="LOWROLE")
    RolePermissionFactory(role=low, permission=permission, perm_level=0, if_owner=False)
    high_own = RoleFactory(code="HIGHOWNROLE")
    RolePermissionFactory(role=high_own, permission=permission, perm_level=2, if_owner=True)
    UserRoleFactory(user=user, role=low)
    UserRoleFactory(user=user, role=high_own)
    invalidate_permission_cache(user)

    resolved = {g for g in resolve_permissions(user) if g.resource == "employee_document"}
    assert Grant("employee_document", "view", 0, False) in resolved
    assert Grant("employee_document", "view", 2, True) in resolved
    assert Grant("employee_document", "view", 2, False) not in resolved

    # And the consequence that actually matters:
    other = UserAccountFactory()
    assert has_permission(user, "employee_document", "view", obj=other, level=2) is False
    assert has_permission(user, "employee_document", "view", obj=user, level=2) is True


@pytest.mark.django_db
def test_inactive_role_is_excluded():
    user = UserAccountFactory()
    role = grant(user, "client", "view")

    assert has_permission(user, "client", "view") is True

    role.is_active = False
    role.save(update_fields=["is_active"])
    invalidate_permission_cache(user)

    assert resolve_permissions(user) == frozenset()


@pytest.mark.django_db
def test_inactive_user_holds_nothing():
    user = UserAccountFactory()
    grant(user, "client", "view")

    user.is_active = False
    invalidate_permission_cache(user)

    assert resolve_permissions(user) == frozenset()


@pytest.mark.django_db
def test_soft_deleted_user_holds_nothing():
    from django.utils import timezone

    user = UserAccountFactory()
    grant(user, "client", "view")

    user.deleted_at = timezone.now()
    invalidate_permission_cache(user)

    assert resolve_permissions(user) == frozenset()


@pytest.mark.django_db
def test_anonymous_holds_nothing():
    from django.contrib.auth.models import AnonymousUser

    assert resolve_permissions(None) == frozenset()
    assert resolve_permissions(AnonymousUser()) == frozenset()


# --- has_permission and the if_owner path ------------------------------------


@pytest.mark.django_db
def test_if_owner_permits_own_record_and_refuses_another():
    """The core of `own`: a user may edit their own record and not somebody else's."""
    user = UserAccountFactory()
    other = UserAccountFactory()
    grant(user, constants.RES_PASSWORD, "edit", if_owner=True)

    assert has_permission(user, constants.RES_PASSWORD, "edit", obj=user) is True
    assert has_permission(user, constants.RES_PASSWORD, "edit", obj=other) is False


@pytest.mark.django_db
def test_owner_scoped_grant_refuses_when_no_object_is_supplied():
    """"May you edit a record" cannot be answered yes when the truth is
    "only your own"."""
    user = UserAccountFactory()
    grant(user, constants.RES_PASSWORD, "edit", if_owner=True)

    assert has_permission(user, constants.RES_PASSWORD, "edit") is False


@pytest.mark.django_db
def test_employee_ownership_follows_the_user_to_their_employee_row():
    user = UserAccountFactory()
    grant(user, constants.RES_EMPLOYEE, "view", if_owner=True)

    assert has_permission(user, constants.RES_EMPLOYEE, "view", obj=user.employee) is True
    assert has_permission(
        user, constants.RES_EMPLOYEE, "view", obj=EmployeeFactory()
    ) is False


@pytest.mark.django_db
def test_level_is_a_floor_not_an_equality():
    user = UserAccountFactory()
    grant(user, constants.RES_EMPLOYEE, "edit", level=1)

    assert has_permission(user, constants.RES_EMPLOYEE, "edit", level=0) is True
    assert has_permission(user, constants.RES_EMPLOYEE, "edit", level=1) is True
    assert has_permission(user, constants.RES_EMPLOYEE, "edit", level=2) is False


# --- account creation ---------------------------------------------------------


@pytest.mark.django_db
def test_account_creation_succeeds_for_a_holder_of_user_account_create():
    actor = UserAccountFactory()
    grant(actor, constants.RES_USER_ACCOUNT, "create")
    employee = EmployeeFactory()

    account, password = create_user_account(actor, employee, "newjoiner")

    assert account.username == "newjoiner"
    assert account.employee_id == employee.id
    assert account.must_change_password is True
    assert account.created_by_id == actor.id
    assert account.check_password(password)


@pytest.mark.django_db
def test_account_creation_raises_for_everyone_else():
    actor = UserAccountFactory()
    grant(actor, constants.RES_CLIENT, "view")  # some unrelated authority
    employee = EmployeeFactory()

    with pytest.raises(PermissionDenied):
        create_user_account(actor, employee, "shouldnotexist")

    assert not UserAccount.objects.filter(username="shouldnotexist").exists()


@pytest.mark.django_db
def test_one_account_per_employee():
    actor = UserAccountFactory()
    grant(actor, constants.RES_USER_ACCOUNT, "create")
    employee = EmployeeFactory()
    create_user_account(actor, employee, "firstlogin")

    with pytest.raises(RuleViolation):
        create_user_account(actor, employee, "secondlogin")


@pytest.mark.django_db
def test_usernames_are_case_insensitive():
    """citext, not varchar. 'Asha' and 'asha' are the same login."""
    actor = UserAccountFactory()
    grant(actor, constants.RES_USER_ACCOUNT, "create")
    create_user_account(actor, EmployeeFactory(), "Asha")

    with pytest.raises(RuleViolation):
        create_user_account(actor, EmployeeFactory(), "asha")


# --- password change ----------------------------------------------------------


@pytest.mark.django_db
def test_changing_own_password_succeeds():
    user = UserAccountFactory(password="old-password-value")
    grant(user, constants.RES_PASSWORD, "edit", if_owner=True)

    change_own_password(user, "old-password-value", "a-much-longer-new-secret")

    user.refresh_from_db()
    assert user.check_password("a-much-longer-new-secret")
    assert user.must_change_password is False
    assert user.password_changed_at is not None


@pytest.mark.django_db
def test_changing_password_with_the_wrong_current_password_raises():
    user = UserAccountFactory(password="old-password-value")
    grant(user, constants.RES_PASSWORD, "edit", if_owner=True)

    with pytest.raises(PermissionDenied):
        change_own_password(user, "not-the-current-one", "a-much-longer-new-secret")

    user.refresh_from_db()
    assert user.check_password("old-password-value")


@pytest.mark.django_db
def test_password_validators_are_djangos_not_ours():
    user = UserAccountFactory(password="old-password-value")
    grant(user, constants.RES_PASSWORD, "edit", if_owner=True)

    with pytest.raises(RuleViolation):
        change_own_password(user, "old-password-value", "short")


@pytest.mark.django_db
def test_a_user_without_password_edit_cannot_change_even_their_own():
    user = UserAccountFactory(password="old-password-value")

    with pytest.raises(PermissionDenied):
        change_own_password(user, "old-password-value", "a-much-longer-new-secret")


# --- role assignment ----------------------------------------------------------


@pytest.mark.django_db
def test_assign_and_revoke_role():
    actor = UserAccountFactory()
    grant(actor, constants.RES_ROLE_ASSIGNMENT, "create")
    grant(actor, constants.RES_ROLE_ASSIGNMENT, "delete")
    target = UserAccountFactory()
    role = RoleFactory(code="TARGETROLE")

    assignment = assign_role(actor, target, role)
    assert assignment.assigned_by_id == actor.id
    assert UserRole.objects.filter(user=target, role=role).exists()

    revoke_role(actor, target, role)
    assert not UserRole.objects.filter(user=target, role=role).exists()


@pytest.mark.django_db
def test_assigning_a_role_without_authority_raises():
    actor = UserAccountFactory()
    target = UserAccountFactory()
    role = RoleFactory(code="FORBIDDENROLE")

    with pytest.raises(PermissionDenied):
        assign_role(actor, target, role)


@pytest.mark.django_db
def test_assigning_an_inactive_role_raises():
    actor = UserAccountFactory()
    grant(actor, constants.RES_ROLE_ASSIGNMENT, "create")
    role = RoleFactory(code="DORMANTROLE", is_active=False)

    with pytest.raises(RuleViolation):
        assign_role(actor, UserAccountFactory(), role)


@pytest.mark.django_db
def test_duplicate_assignment_raises_rather_than_silently_passing():
    actor = UserAccountFactory()
    grant(actor, constants.RES_ROLE_ASSIGNMENT, "create")
    target = UserAccountFactory()
    role = RoleFactory(code="ONCEONLY")

    assign_role(actor, target, role)
    with pytest.raises(RuleViolation):
        assign_role(actor, target, role)


# --- the seeded grid ----------------------------------------------------------


@pytest.mark.django_db
def test_the_nine_roles_are_seeded():
    codes = set(Role.objects.filter(is_system=True).values_list("code", flat=True))
    assert codes == {code for code, _ in constants.ROLES}
    assert len(codes) == 9


@pytest.mark.django_db
def test_the_grid_is_seeded_completely():
    expected = list(constants.iter_grants())
    assert RolePermission.objects.count() >= len(expected)

    for resource, action, role_code, perm_level, if_owner in expected:
        assert RolePermission.objects.filter(
            role__code=role_code,
            permission__resource=resource,
            permission__action=action,
            perm_level=perm_level,
            if_owner=if_owner,
        ).exists(), f"missing grant {role_code} -> {resource}:{action}@{perm_level}"


@pytest.mark.django_db
def test_owner_role_can_create_accounts_and_sales_cannot():
    """D3 expressed as a permission, verified against the seeded grid."""
    owner = UserAccountFactory()
    UserRoleFactory(user=owner, role=Role.objects.get(code=constants.ROLE_OWNER))
    salesperson = UserAccountFactory()
    UserRoleFactory(user=salesperson, role=Role.objects.get(code=constants.ROLE_SALES))

    assert has_permission(owner, constants.RES_USER_ACCOUNT, "create") is True
    assert has_permission(salesperson, constants.RES_USER_ACCOUNT, "create") is False


@pytest.mark.django_db
def test_hr_role_can_create_accounts():
    """The ninth role D3 adds. If this fails, D3 was silently reverted."""
    hr = UserAccountFactory()
    UserRoleFactory(user=hr, role=Role.objects.get(code=constants.ROLE_HR))

    assert has_permission(hr, constants.RES_USER_ACCOUNT, "create") is True


@pytest.mark.django_db
def test_accounts_role_can_attach_quotation_pdf():
    """ACCT attaches a quotation PDF via the same quotation:create grant Sales
    uses. If this fails, migration 0005 was silently reverted."""
    accountant = UserAccountFactory()
    UserRoleFactory(user=accountant, role=Role.objects.get(code=constants.ROLE_ACCT))

    assert has_permission(accountant, constants.RES_QUOTATION, "create") is True


@pytest.mark.django_db
def test_sales_can_no_longer_create_quotations():
    """Sales adds enquiries and views/downloads quotations; quotation creation
    is Accounts'/Owner's job. If this fails, migration 0007 was silently
    reverted."""
    salesperson = UserAccountFactory()
    UserRoleFactory(user=salesperson, role=Role.objects.get(code=constants.ROLE_SALES))

    assert has_permission(salesperson, constants.RES_QUOTATION, "create") is False
    assert has_permission(salesperson, constants.RES_QUOTATION, "view") is True
    assert has_permission(salesperson, constants.RES_JOB_CARD, "create") is True


@pytest.mark.django_db
def test_sales_only_sees_their_own_job_cards():
    """Prevents client poaching between reps. If this fails, migration 0008
    was silently reverted."""
    rep_a = UserAccountFactory()
    rep_b = UserAccountFactory()
    UserRoleFactory(user=rep_a, role=Role.objects.get(code=constants.ROLE_SALES))
    UserRoleFactory(user=rep_b, role=Role.objects.get(code=constants.ROLE_SALES))

    own_card = JobCardFactory(owner_user=rep_a, client=ClientFactory())
    others_card = JobCardFactory(owner_user=rep_b, client=ClientFactory())

    assert has_permission(rep_a, constants.RES_JOB_CARD, "view", obj=own_card) is True
    assert has_permission(rep_a, constants.RES_JOB_CARD, "view", obj=others_card) is False
    # No obj at all reads as "no" for an owner-scoped-only grant — the list
    # endpoints use owner_scope_for, not a bare has_permission, for exactly
    # this reason.
    assert has_permission(rep_a, constants.RES_JOB_CARD, "view") is False

    assert owner_scope_for(rep_a, constants.RES_JOB_CARD, "view") == rep_a
    owner = UserAccountFactory()
    UserRoleFactory(user=owner, role=Role.objects.get(code=constants.ROLE_OWNER))
    assert owner_scope_for(owner, constants.RES_JOB_CARD, "view") is None


@pytest.mark.django_db
def test_admin_and_hr_can_add_clients_from_the_django_admin():
    """Only OWNER held both admin_site:view and client:create before migration
    0006 — ADMIN/HR could sign into /admin/ but never saw an "Add client"
    button there. If this fails, 0006 was silently reverted."""
    for role_code in (constants.ROLE_ADMIN, constants.ROLE_HR):
        user = UserAccountFactory()
        UserRoleFactory(user=user, role=Role.objects.get(code=role_code))

        assert has_permission(user, constants.RES_CLIENT, "create") is True


@pytest.mark.django_db
def test_every_seeded_permission_action_is_in_the_check_domain():
    """ck_permissions_action would have rejected anything else at insert time,
    so this really asserts the grid never tried to invent a verb."""
    from apps.identity.models import PermissionAction

    actions = set(Permission.objects.values_list("action", flat=True))
    assert actions <= set(PermissionAction.values)


@pytest.mark.django_db
def test_operational_roles_get_only_their_own_employee_record():
    """"Employees may change their own password and nothing else about their
    profile" — expressed as the absence of an employee:edit grant, not as a
    special case in code."""
    for role_code in (
        constants.ROLE_SALES,
        constants.ROLE_DESIGN,
        constants.ROLE_PROD,
        constants.ROLE_PURCH,
        constants.ROLE_STORE,
        constants.ROLE_ACCT,
    ):
        user = UserAccountFactory()
        UserRoleFactory(user=user, role=Role.objects.get(code=role_code))

        assert has_permission(user, constants.RES_EMPLOYEE, "view", obj=user.employee)
        assert not has_permission(
            user, constants.RES_EMPLOYEE, "view", obj=EmployeeFactory()
        )
        assert not has_permission(user, constants.RES_EMPLOYEE, "edit", obj=user.employee)
