"""Grant ``client:create`` to ADMIN and HR, alongside OWNER/SALES.

Same reasoning as 0005: this pair already existed (seeded by 0002 for
OWNER/SALES) — this migration only adds ADMIN's and HR's grants, so
``unseed`` removes just those two RolePermission rows rather than the
whole Permission.

Without this, ADMIN and HR could sign into the Django admin
(``admin_site:view``) but never see an "Add client" button there — only
OWNER held both permissions needed to add a client from ``/admin/``.
"""

from django.db import migrations

from apps.identity.constants import (
    PERMISSION_DESCRIPTIONS,
    RES_CLIENT,
    iter_grants,
)

_RESOURCE, _ACTION = RES_CLIENT, "create"
_NEW_ROLES = ("ADMIN", "HR")


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
        if (resource, action) != (_RESOURCE, _ACTION) or role_code not in _NEW_ROLES:
            continue
        role = Role.objects.get(code=role_code)
        RolePermission.objects.update_or_create(
            role=role,
            permission=permission,
            perm_level=perm_level,
            defaults={"if_owner": if_owner},
        )


def unseed(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission = Permission.objects.filter(resource=_RESOURCE, action=_ACTION).first()
    if permission is not None:
        RolePermission.objects.filter(
            role__code__in=_NEW_ROLES, permission=permission
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0005_accounts_quotation_create_permission"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
