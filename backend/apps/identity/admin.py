"""Admin for accounts, roles, permissions and grants."""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages

from apps.core.admin import RBACModelAdmin, ReadOnlyAdmin
from apps.identity import constants
from apps.identity.models import (
    LoginSession,
    Permission,
    Role,
    RolePermission,
    UserAccount,
    UserRole,
)
from apps.identity.services import create_user_account, has_permission


class UserAccountAdminForm(forms.ModelForm):
    """Adds a form-only `role` field — UserAccount itself carries no role
    column (roles are the separate UserRole model) — so a new login can be
    assigned one in the same step it's created. Without this, a fresh
    account has zero roles and therefore zero grants, including
    password:edit on its own row: the new user can't even complete the
    forced first-login password change until someone assigns a role
    afterwards through Role assignments.
    """

    role = forms.ModelChoiceField(
        queryset=Role.objects.filter(is_active=True).order_by("code"),
        required=False,
        help_text=(
            "Assigned to the account immediately, if you hold role-assignment "
            "authority. Leave blank to assign one later from Role assignments — "
            "but note an account with no role can't do anything yet, including "
            "change its own password."
        ),
    )


@admin.register(UserAccount)
class UserAccountAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_USER_ACCOUNT
    form = UserAccountAdminForm
    list_display = ("username", "employee", "is_active", "must_change_password",
                    "failed_login_count", "locked_until", "last_login")
    list_filter = ("is_active", "must_change_password")
    search_fields = ("username", "employee__full_name", "employee__employee_code")
    ordering = ("username",)
    autocomplete_fields = ("employee", "created_by")
    # password_hash is never shown or edited here. Rotation goes through
    # identity.services.set_password_for, which runs Django's validators.
    exclude = ("password",)
    readonly_fields = ("last_login", "password_changed_at", "created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("employee")

    def get_fields(self, request, obj=None):
        """`role` only makes sense at creation — dropping it for edits keeps
        role changes in one place (Role assignments), the same reasoning
        RBACModelAdmin's trailing-field reorder already applies to the real
        model fields here."""
        fields = list(super().get_fields(request, obj))
        if obj is not None:
            return [f for f in fields if f != "role"]
        if "role" not in fields:
            idx = fields.index("username") + 1 if "username" in fields else len(fields)
            fields.insert(idx, "role")
        return fields

    def save_model(self, request, obj, form, change):
        """Route new accounts through create_user_account so they get a real,
        hashed password — the admin form excludes `password` entirely, so
        obj.save() alone would leave the login unusable (apps/identity/
        models.py's UserAccountManager is the only thing allowed to hash one).
        """
        if change:
            super().save_model(request, obj, form, change)
            return

        account, password = create_user_account(request.user, obj.employee, obj.username)
        obj.pk = account.pk
        obj.__dict__.update(account.__dict__)
        messages.warning(
            request,
            f"Password for {account.username}: {password} "
            "— shown once, copy it now. The user must change it on first login.",
        )

        role = form.cleaned_data.get("role")
        if role is None:
            return
        if not has_permission(request.user, constants.RES_ROLE_ASSIGNMENT, "create"):
            messages.warning(
                request,
                f"{account.username} was created, but you don't hold role-assignment "
                "authority — ask an Owner or Admin to assign a role before this "
                "account can do anything, including change its own password.",
            )
            return
        UserRole.objects.create(user=account, role=role, assigned_by=request.user)


@admin.register(Role)
class RoleAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_ROLE_ASSIGNMENT
    list_display = ("code", "name", "is_system", "is_active")
    list_filter = ("is_active", "is_system")
    search_fields = ("code", "name")
    ordering = ("code",)

    def has_delete_permission(self, request, obj=None) -> bool:
        """A system role is referenced by the seeded grid and by transition
        rules; deleting one would fail on ON DELETE RESTRICT anyway, so refuse
        it in a place that can explain itself."""
        if obj is not None and obj.is_system:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Permission)
class PermissionAdmin(ReadOnlyAdmin):
    """The catalogue is seeded by a migration. Adding a row here would create
    a permission no code asks about; the honest way to add one is a migration."""

    rbac_resource = constants.RES_ROLE_ASSIGNMENT
    list_display = ("resource", "action", "description")
    list_filter = ("action", "resource")
    search_fields = ("resource", "action")
    ordering = ("resource", "action")


@admin.register(RolePermission)
class RolePermissionAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_ROLE_ASSIGNMENT
    list_display = ("role", "permission", "perm_level", "if_owner")
    list_filter = ("perm_level", "if_owner", "role")
    search_fields = ("role__code", "permission__resource", "permission__action")
    ordering = ("role__code", "permission__resource")
    autocomplete_fields = ("role", "permission")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("role", "permission")


@admin.register(UserRole)
class UserRoleAdmin(RBACModelAdmin):
    rbac_resource = constants.RES_ROLE_ASSIGNMENT
    list_display = ("user", "role", "assigned_by", "assigned_at")
    list_filter = ("role",)
    search_fields = ("user__username", "role__code")
    ordering = ("user__username",)
    autocomplete_fields = ("user", "role", "assigned_by")
    readonly_fields = ("assigned_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "role", "assigned_by")

    def save_model(self, request, obj, form, change):
        """Record who granted this, if the form did not say."""
        if not change and obj.assigned_by_id is None:
            obj.assigned_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(LoginSession)
class LoginSessionAdmin(ReadOnlyAdmin):
    """D11: this table is created and left empty. Nothing issues refresh
    tokens — browser sessions live in django_session — so this is a window
    onto a table that should stay at zero rows until a mobile or third-party
    client exists."""

    rbac_resource = constants.RES_USER_ACCOUNT
    list_display = ("user", "issued_at", "expires_at", "revoked_at", "ip_address")
    search_fields = ("user__username",)
    ordering = ("-issued_at",)


# Searchable targets for the autocomplete_fields above.
UserAccountAdmin.search_fields = ("username", "employee__full_name",
                                  "employee__employee_code")
RoleAdmin.search_fields = ("code", "name")
PermissionAdmin.search_fields = ("resource", "action")
