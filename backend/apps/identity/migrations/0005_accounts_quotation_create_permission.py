"""Grant ``quotation:create`` to ACCT (Accounts), alongside OWNER/SALES.

Same reasoning as 0003/0004: earlier migrations already ran and won't
re-execute, so a grid addition needs its own migration. Lets Accounts
attach a quotation PDF to a job card the same way Sales already does
(``apps.sales.services.create_quotation_revision``) — scoped to exactly
this one (resource, action) pair.

Unlike 0003/0004, this pair already existed (seeded by 0002 for
OWNER/SALES) — this migration only adds ACCT's grant, so ``unseed`` removes
just that RolePermission row rather than the whole Permission.
"""

from django.db import migrations

from apps.identity.constants import (
    PERMISSION_DESCRIPTIONS,
    RES_QUOTATION,
    iter_grants,
)

_RESOURCE, _ACTION = RES_QUOTATION, "create"


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
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission = Permission.objects.filter(resource=_RESOURCE, action=_ACTION).first()
    if permission is not None:
        role = Role.objects.get(code="ACCT")
        RolePermission.objects.filter(role=role, permission=permission).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0004_employee_delete_permission"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
