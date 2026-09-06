"""Add ``user_account:view`` (Owner/Admin/HR) to the permission grid.

0002 already ran and won't re-execute, so a grid addition needs its own
migration. Without a ``view`` grant, Django admin's ``AutocompleteJsonView``
(which checks ``has_view_permission`` strictly, unlike the changelist) always
403s on any field that autocompletes against ``UserAccount`` — e.g. the
"User" field on a role assignment — even for Owner. Scoped to exactly this
one (resource, action) pair rather than re-running the whole grid seed, so a
later addition to GRID still needs its own migration too.
"""

from django.db import migrations

from apps.identity.constants import (
    PERMISSION_DESCRIPTIONS,
    RES_USER_ACCOUNT,
    iter_grants,
)

_RESOURCE, _ACTION = RES_USER_ACCOUNT, "view"


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
        ("identity", "0002_roles_and_permission_grid"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
