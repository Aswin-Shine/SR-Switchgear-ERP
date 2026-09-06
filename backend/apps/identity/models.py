"""identity — login accounts, roles, permissions.

Tables: auth_user_accounts, auth_sessions, auth_roles, auth_permissions,
auth_user_roles, auth_role_permissions.

A naming hazard worth stating plainly (deviation 3.12): ``django.contrib.auth``
creates ``auth_permission`` (singular). Ours is ``auth_permissions`` (plural).
They differ by one character and hold unrelated data. The prompt specifies the
``auth_`` prefix, so this follows it; if the ambiguity ever bites, renaming ours
to ``identity_*`` is a decision to take before the first production migrate,
not after.
"""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

from apps.core.fields import CITextField, Now, uuid_pk_kwargs
from apps.core.models import TimeStamped, fk


class PermissionAction(models.TextChoices):
    """The verbs ``ck_permissions_action`` allows.

    One of the four status domains the database itself pins with a CHECK, so
    declaring it once here and referencing it symbolically is the deliberate,
    bounded exception to "no string literals in application logic"
    (BACKEND_PLAN.md section 4). A new verb needs a migration.
    """

    VIEW = "view", "View"
    CREATE = "create", "Create"
    EDIT = "edit", "Edit"
    DELETE = "delete", "Delete"
    SUBMIT = "submit", "Submit"
    CANCEL = "cancel", "Cancel"
    APPROVE = "approve", "Approve"
    RELEASE = "release", "Release"
    EXPORT = "export", "Export"
    PRINT = "print", "Print"
    SHARE = "share", "Share"


class Role(TimeStamped):
    """Coarse-grained roles. Express exceptions through role_permissions,
    not by minting new roles."""

    id = models.UUIDField(**uuid_pk_kwargs())
    code = CITextField()
    name = models.TextField()
    is_system = models.BooleanField(
        db_default=False,
        default=False,
        help_text="Seeded by a migration. Deleting one breaks the permission grid.",
    )
    is_active = models.BooleanField(db_default=True, default=True)

    class Meta:
        db_table = "auth_roles"
        default_permissions = ()
        verbose_name = "role"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uk_roles_code"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Permission(models.Model):
    """An atomic (resource, action) capability, e.g. ('quotation', 'approve').

    Not to be confused with ``django.contrib.auth.models.Permission``.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    resource = models.TextField()
    action = models.TextField(choices=PermissionAction.choices)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "auth_permissions"
        default_permissions = ()
        verbose_name = "permission"
        ordering = ["resource", "action"]
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "action"], name="uk_permissions_resource_action"
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=PermissionAction.values),
                name="ck_permissions_action",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.resource}:{self.action}"


class UserAccountManager(BaseUserManager):
    """``createsuperuser`` is deliberately not supported.

    ``auth_user_accounts.employee_id`` is NOT NULL, so an account cannot exist
    without an employee, and an employee cannot exist without a department and
    a designation. There is no way to conjure the first account from thin air —
    which is exactly why ``manage.py bootstrap_admin`` exists: it creates the
    whole chain in one transaction.
    """

    use_in_migrations = False

    def create_user(self, username: str, employee, password: str | None = None, **extra):
        if not username:
            raise ValueError("A user account requires a username")
        if employee is None:
            raise ValueError(
                "A user account requires an employee — auth_user_accounts.employee_id "
                "is NOT NULL. Use `manage.py bootstrap_admin` for the first account."
            )
        user = self.model(username=username, employee=employee, **extra)
        # Django's hashers and validators, never our own.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, *args, **kwargs):
        raise NotImplementedError(
            "This project has no is_superuser column. Authority comes from roles in "
            "auth_role_permissions. Use `manage.py bootstrap_admin` instead."
        )


class UserAccount(AbstractBaseUser):
    """A login. Optional per employee — floor staff may have none.

    Deviation 3.11 in full: Django's admin calls ``request.user.is_staff`` and
    ``request.user.has_perm("app.codename")``. ``AbstractBaseUser`` provides
    neither, and ``auth_user_accounts`` has no ``is_staff`` column. Rather than
    add one — which would put authority in two places — ``is_staff`` is derived
    from the ``admin_site:view`` permission, and the ``has_perm`` family routes
    into ``identity.services.has_permission``. No schema change.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    employee = fk(
        "hr.Employee", models.PROTECT, related_name="user_account",
        help_text="NOT NULL: every login belongs to exactly one employee.",
    )
    username = CITextField()

    # AbstractBaseUser declares `password` as CharField(max_length=128) and
    # `last_login` as `last_login`. The schema says TEXT / last_login_at.
    # Overriding a concrete field inherited from an abstract base is allowed.
    password = models.TextField(db_column="password_hash")
    last_login = models.DateTimeField(db_column="last_login_at", null=True, blank=True)

    is_active = models.BooleanField(db_default=True, default=True)
    must_change_password = models.BooleanField(db_default=True, default=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)

    # Login throttling state. No rate-limiting dependency needed: these columns
    # already exist (BACKEND_PLAN.md section 7).
    failed_login_count = models.SmallIntegerField(db_default=0, default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    created_by = fk(
        "self", models.SET_NULL, null=True, blank=True,
        db_column="created_by", related_name="created_accounts",
    )
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(db_default=Now(), editable=False)
    deleted_at = models.DateTimeField(null=True, blank=True, default=None)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    objects = UserAccountManager()

    class Meta:
        db_table = "auth_user_accounts"
        default_permissions = ()
        verbose_name = "user account"
        constraints = [
            models.UniqueConstraint(fields=["username"], name="uk_user_accounts_username"),
            models.UniqueConstraint(fields=["employee"], name="uk_user_accounts_employee"),
            models.CheckConstraint(
                condition=models.Q(username__length__gte=3)
                & models.Q(username__length__lte=64),
                name="ck_user_accounts_username",
            ),
            models.CheckConstraint(
                condition=models.Q(failed_login_count__gte=0),
                name="ck_user_accounts_failed",
            ),
        ]

    def __str__(self) -> str:
        return self.username

    # --- The admin's four demands (deviation 3.11) --------------------------

    @property
    def is_staff(self) -> bool:
        """Derived, not stored. Holding ``admin_site:view`` is what admits you."""
        from apps.identity.services import has_permission

        return has_permission(self, "admin_site", "view")

    @property
    def is_superuser(self) -> bool:
        """No such concept. Authority is a grant, never a flag."""
        return False

    def has_perm(self, perm: str, obj=None) -> bool:
        """Route Django's ``"app_label.codename"`` string into our RBAC.

        The admin calls this with strings like ``"hr.view_employee"``. We map
        that to ``(resource, action)`` and answer from auth_role_permissions.
        ``RBACModelAdmin`` calls ``has_permission`` directly and does not rely
        on this translation; it exists for the admin internals we do not own.
        """
        from apps.identity.services import has_permission_for_django_codename

        return has_permission_for_django_codename(self, perm, obj=obj)

    def has_perms(self, perm_list, obj=None) -> bool:
        return all(self.has_perm(perm, obj) for perm in perm_list)

    def has_module_perms(self, app_label: str) -> bool:
        """Whether the app appears in the admin index at all."""
        from apps.identity.services import has_any_permission_in_app

        return has_any_permission_in_app(self, app_label)


class UserRole(models.Model):
    """Assignment of a role to a user.

    Deviation 3.8: the schema's primary key is ``(user_id, role_id)``. Django's
    admin refuses composite-PK models outright — *"The model X has a composite
    primary key, so it cannot be registered with admin."* — and this table must
    be administrable. So it takes a surrogate UUID key and the natural key is
    demoted to a UNIQUE constraint, which enforces exactly the same rule.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    user = fk("identity.UserAccount", models.CASCADE, related_name="user_roles")
    role = fk("identity.Role", models.PROTECT, related_name="user_roles")
    assigned_by = fk(
        "identity.UserAccount", models.SET_NULL, null=True, blank=True,
        db_column="assigned_by", related_name="role_assignments_made",
    )
    assigned_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "auth_user_roles"
        default_permissions = ()
        verbose_name = "role assignment"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="uk_user_roles"),
        ]
        indexes = [
            models.Index(fields=["role"], name="idx_user_roles_role"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} -> {self.role_id}"


class RolePermission(models.Model):
    """A grant: this role may do this thing, at this level, maybe only to its own rows.

    Deviation 3.8, and the subtle half of it: the schema's PK is
    ``(role_id, permission_id, perm_level)``. The demoted unique constraint must
    cover **all three** columns. Dropping ``perm_level`` from it would silently
    forbid multi-tier grants — a role could then hold ``employee:view`` at
    level 0 or level 1, but never both, and the grid in Appendix B needs both.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    role = fk("identity.Role", models.CASCADE, related_name="role_permissions")
    permission = fk("identity.Permission", models.CASCADE, related_name="role_permissions")
    perm_level = models.SmallIntegerField(
        db_default=0,
        default=0,
        help_text="0 = ordinary fields, 1 = protected employee fields, "
                  "2 = sensitive documents (Appendix B).",
    )
    if_owner = models.BooleanField(
        db_default=False,
        default=False,
        help_text="Grant applies only to rows the user owns.",
    )

    class Meta:
        db_table = "auth_role_permissions"
        default_permissions = ()
        verbose_name = "role permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission", "perm_level"], name="uk_role_permissions"
            ),
            models.CheckConstraint(
                condition=models.Q(perm_level__gte=0) & models.Q(perm_level__lte=9),
                name="ck_role_permissions_level",
            ),
        ]
        indexes = [
            models.Index(fields=["permission"], name="idx_role_permissions_perm"),
        ]

    def __str__(self) -> str:
        suffix = " (own rows)" if self.if_owner else ""
        return f"{self.role_id} may {self.permission_id} @L{self.perm_level}{suffix}"


class LoginSession(models.Model):
    """Revocable refresh sessions.

    D11: this table is created and left empty. The prompt forbids JWT and
    mandates Django's own session framework, so browser sessions live in
    ``django_session`` and nothing issues the refresh tokens this table was
    designed to hold. It is modelled rather than dropped because the schema
    defines it and a mobile or third-party client would need it.

    Named ``LoginSession``, not ``Session``, to avoid a collision of meaning
    with ``django.contrib.sessions.models.Session``.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    user = fk("identity.UserAccount", models.CASCADE, related_name="login_sessions")
    refresh_token_hash = models.TextField()
    issued_at = models.DateTimeField(db_default=Now(), editable=False)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "auth_sessions"
        default_permissions = ()
        verbose_name = "login session"
        constraints = [
            models.UniqueConstraint(fields=["refresh_token_hash"], name="uk_sessions_token"),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("issued_at")),
                name="ck_sessions_expiry",
            ),
        ]
        indexes = [
            models.Index(fields=["user"], name="idx_sessions_user"),
        ]

    def __str__(self) -> str:
        return f"session for {self.user_id} until {self.expires_at:%Y-%m-%d}"
