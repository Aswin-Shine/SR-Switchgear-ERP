"""Grant ``sheet_export:view`` to OWNER and ACCT only.

Backs the sidebar link to the Google Sheets job-card ledger
(``apps.core.sheets.sheet_url``, ``apps.identity.api.serialize_me``'s
``sheet_export_url`` field) — a brand new resource, not an addition to an
existing one, so this seeds both the ``Permission`` row and its two grants
in one migration, same shape as 0002's original seed but scoped to just
this pair.
"""

from django.db import migrations

from apps.identity.constants import (
    PERMISSION_DESCRIPTIONS,
    RES_SHEET_EXPORT,
    iter_grants,
)

_RESOURCE, _ACTION = RES_SHEET_EXPORT, "view"


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
    RolePermission = apps.get_model("identity", "RolePermission")

    permission = Permission.objects.filter(resource=_RESOURCE, action=_ACTION).first()
    if permission is not None:
        RolePermission.objects.filter(permission=permission).delete()
        permission.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0009_remove_quotation_approve_and_share_permissions"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
