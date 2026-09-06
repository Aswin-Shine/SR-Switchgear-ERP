"""Revoke ``quotation:create`` from SALES.

User's decision: Sales-role accounts (e.g. Govind Singh) should only add
enquiries (``job_card:create``, still held by SALES) and view/download
quotation PDFs (``quotation:view``, still held by SALES) — not create the
quotation itself. The two accounts that actually create quotations
(Rajendra Saini, Sharad Kumar) were moved to ACCT, which already held
``quotation:create`` since 0005.

Same scoped, single-``(resource, action)``-pair pattern as 0003-0006.
Unlike 0005/0006 (which *added* a role's grant), this migration *removes*
one — ``seed`` deletes the SALES ``RolePermission`` row, ``unseed``
recreates it at the level/if_owner a plain ``Y`` cell always meant
(``LEVEL_ORDINARY``, ``if_owner=False``), matching what 0002 originally
seeded and what ``constants.py`` encoded before this migration.
"""

from django.db import migrations

from apps.identity.constants import (
    LEVEL_ORDINARY,
    PERMISSION_DESCRIPTIONS,
    RES_QUOTATION,
    ROLE_SALES,
)

_RESOURCE, _ACTION = RES_QUOTATION, "create"


def seed(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission = Permission.objects.filter(resource=_RESOURCE, action=_ACTION).first()
    if permission is not None:
        RolePermission.objects.filter(
            role__code=ROLE_SALES, permission=permission
        ).delete()


def unseed(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission, _ = Permission.objects.update_or_create(
        resource=_RESOURCE,
        action=_ACTION,
        defaults={"description": PERMISSION_DESCRIPTIONS[(_RESOURCE, _ACTION)]},
    )
    role = Role.objects.get(code=ROLE_SALES)
    RolePermission.objects.update_or_create(
        role=role,
        permission=permission,
        perm_level=LEVEL_ORDINARY,
        defaults={"if_owner": False},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0006_admin_hr_client_create_permission"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
