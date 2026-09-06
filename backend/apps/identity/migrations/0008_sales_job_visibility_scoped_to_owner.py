"""Scope SALES' job_card:view and job_line:view to their own rows.

User's request: a Sales rep should see their own enquiries and pipeline
lines, not every other Sales rep's — an unrestricted view grant let anyone
in SALES browse (and, on the board, see the client name on) every other
rep's active deal, which is exactly the "client poaching" risk they flagged.

Same scoped pattern as 0003-0007, except this one changes `if_owner` on an
existing (role, permission) row rather than adding or removing the row
itself — `seed()` flips it True, `unseed()` flips it back to False, which is
what a plain `Y` cell always meant (LEVEL_ORDINARY, if_owner=False).
"""

from django.db import migrations

from apps.identity.constants import RES_JOB_CARD, RES_JOB_LINE, ROLE_SALES

_PAIRS = [(RES_JOB_CARD, "view"), (RES_JOB_LINE, "view")]


def _set_if_owner(apps, value: bool) -> None:
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    for resource, action in _PAIRS:
        permission = Permission.objects.filter(resource=resource, action=action).first()
        if permission is not None:
            RolePermission.objects.filter(
                role__code=ROLE_SALES, permission=permission
            ).update(if_owner=value)


def seed(apps, schema_editor):
    _set_if_owner(apps, True)


def unseed(apps, schema_editor):
    _set_if_owner(apps, False)


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0007_sales_loses_quotation_create_permission"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
