"""Add ``employee:delete`` (Owner/Admin/HR) to the permission grid.

Same reasoning as 0003: earlier migrations already ran and won't
re-execute, so a grid addition needs its own migration. Without this,
``has_permission(user, "employee", "delete")`` was False for everyone
including Owner — not a deliberate "employees can never be deleted" policy,
just a resource nobody had gotten around to adding a delete grant for.
Scoped to exactly this one (resource, action) pair, matching 0003.
"""

from django.db import migrations

from apps.identity.constants import (
    PERMISSION_DESCRIPTIONS,
    RES_EMPLOYEE,
    iter_grants,
)

_RESOURCE, _ACTION = RES_EMPLOYEE, "delete"


def seed(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission, _ = Permission.objects.update_or_create(
        resource=_RESOURCE,
        action=_ACTION,
        defaults={"description": PERMISSION_DESCRIPTIONS[(_RESOURCE, _ACTION)]},
    )

    for resource, action, role_code, perm_level, if_owner in iter_grants():
        if (resource, action) != (_RESOURCE, _ACTION):
            continue
        role = Role.objects.get(code=role_code)
        RolePermission.objects.update_or_create(
            role=role,
            permission=permission,
            perm_level=perm_level,
            defaults={"if_owner": if_owner},
        )


def unseed(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")

    # RolePermission rows cascade with the Permission (fk_role_permissions_permission).
    Permission.objects.filter(resource=_RESOURCE, action=_ACTION).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0003_user_account_view_permission"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
