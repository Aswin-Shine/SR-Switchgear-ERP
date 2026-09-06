"""Seed the nine roles, the permission catalogue and the Appendix B grid.

D2 and D3 land here. HR is a ninth role, and the authority to create accounts
is carried by the permission ``user_account:create`` rather than by any
role-name check — so re-answering D3 later is an UPDATE against these rows, not
a code change.

Idempotent, and safe to re-run: every write is get_or_create/update_or_create
keyed on the natural key. The reverse removes only the grants and permissions
this migration knows about, and leaves the roles in place if anyone has been
assigned one.
"""

from django.db import migrations

from apps.identity.constants import (
    PERMISSION_DESCRIPTIONS,
    ROLES,
    iter_grants,
    iter_permissions,
)


def seed(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    roles = {}
    for code, name in ROLES:
        role, _ = Role.objects.update_or_create(
            code=code,
            defaults={"name": name, "is_system": True, "is_active": True},
        )
        roles[code] = role

    permissions = {}
    for resource, action in iter_permissions():
        permission, _ = Permission.objects.update_or_create(
            resource=resource,
            action=action,
            defaults={"description": PERMISSION_DESCRIPTIONS.get((resource, action), "")},
        )
        permissions[(resource, action)] = permission

    for resource, action, role_code, perm_level, if_owner in iter_grants():
        RolePermission.objects.update_or_create(
            role=roles[role_code],
            permission=permissions[(resource, action)],
            perm_level=perm_level,
            defaults={"if_owner": if_owner},
        )


def unseed(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")
    UserRole = apps.get_model("identity", "UserRole")

    resource_actions = list(iter_permissions())
    permission_ids = list(
        Permission.objects.filter(
            id__in=[
                p.id
                for p in Permission.objects.all()
                if (p.resource, p.action) in resource_actions
            ]
        ).values_list("id", flat=True)
    )

    RolePermission.objects.filter(permission_id__in=permission_ids).delete()
    Permission.objects.filter(id__in=permission_ids).delete()

    # Only drop roles nobody holds. Deleting a role out from under a live
    # assignment would fail on fk_user_roles_role (ON DELETE RESTRICT) anyway,
    # and silently reassigning people is worse than leaving a row behind.
    held = set(UserRole.objects.values_list("role_id", flat=True))
    Role.objects.filter(
        code__in=[code for code, _ in ROLES], is_system=True
    ).exclude(id__in=held).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
