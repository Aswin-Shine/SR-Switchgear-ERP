"""Remove ``quotation:approve`` and ``quotation:share`` entirely.

Companion to ``sales/migrations/0002_remove_quotation_status_machine.py``:
that migration deletes ``activate_quotation``/``send_quotation``, the only
things ``quotation:approve``/``quotation:share`` ever gated. Unlike
``0007`` (which revoked one role's grant on a pair that still exists),
these two whole ``(resource, action)`` pairs no longer exist in
``constants.GRID`` at all — a fresh ``0002`` run on an empty database
already won't seed them, but an existing database (this one) ran ``0002``
before this change and needs the stale ``Permission``/``RolePermission``
rows cleaned up explicitly, same as ``0007``'s reasoning.

``approve`` was OWNER-only; ``share`` was OWNER + SALES — exactly what
``constants.GRID`` encoded before this migration, and what ``unseed()``
recreates.
"""

from django.db import migrations

from apps.identity.constants import LEVEL_ORDINARY, ROLE_OWNER, ROLE_SALES

_RESOURCE = "quotation"
_ACTIONS = ("approve", "share")
_ROLES_BY_ACTION = {
    "approve": [ROLE_OWNER],
    "share": [ROLE_OWNER, ROLE_SALES],
}
_DESCRIPTIONS = {
    "approve": "Activate a quotation revision",
    "share": "Send a quotation to the client",
}


def seed(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    for action in _ACTIONS:
        permission = Permission.objects.filter(resource=_RESOURCE, action=action).first()
        if permission is None:
            continue
        RolePermission.objects.filter(permission=permission).delete()
        permission.delete()


def unseed(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    for action in _ACTIONS:
        permission, _ = Permission.objects.update_or_create(
            resource=_RESOURCE,
            action=action,
            defaults={"description": _DESCRIPTIONS[action]},
        )
        for role_code in _ROLES_BY_ACTION[action]:
            role = Role.objects.get(code=role_code)
            RolePermission.objects.update_or_create(
                role=role,
                permission=permission,
                perm_level=LEVEL_ORDINARY,
                defaults={"if_owner": False},
            )


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0008_sales_job_visibility_scoped_to_owner"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
