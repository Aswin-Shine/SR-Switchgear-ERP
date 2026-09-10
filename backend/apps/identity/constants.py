"""Role codes and the permission grid (D2, D3, Appendix B).

These are *seed data expressed as constants*, not business logic. Application
code never compares a role code against a literal — it asks
``has_permission(user, resource, action)``. The codes appear here, in the data
migration that inserts them, and in tests that need to name a role. Nowhere
else.

D3 is settled here in the way the plan recommends: HR is a ninth role, and the
authority to create accounts is the permission ``user_account:create`` rather
than a role-name check. Moving that authority to a different role is then an
UPDATE, not a code change.
"""

from __future__ import annotations

# --- Roles ------------------------------------------------------------------

ROLE_OWNER = "OWNER"
ROLE_ADMIN = "ADMIN"
ROLE_HR = "HR"
ROLE_SALES = "SALES"
ROLE_DESIGN = "DESIGN"
ROLE_PROD = "PROD"
ROLE_PURCH = "PURCH"
ROLE_STORE = "STORE"
ROLE_ACCT = "ACCT"

ROLES: list[tuple[str, str]] = [
    (ROLE_OWNER, "Owner"),
    (ROLE_ADMIN, "Administrator"),
    (ROLE_HR, "HR"),
    (ROLE_SALES, "Sales"),
    (ROLE_DESIGN, "Electrical Designer"),
    (ROLE_PROD, "Production Manager"),
    (ROLE_PURCH, "Purchase"),
    (ROLE_STORE, "Storekeeper"),
    (ROLE_ACCT, "Accounts"),
]

ROLE_ORDER = [code for code, _ in ROLES]

# --- Permission levels ------------------------------------------------------

# The schema says only "0 = normal fields, 1+ = protected". Appendix B gives
# those numbers concrete meaning, and this is the single place that definition
# lives.
LEVEL_ORDINARY = 0
LEVEL_PROTECTED = 1
LEVEL_SENSITIVE = 2

#: Employee fields that require perm_level >= 1 to write.
PROTECTED_EMPLOYEE_FIELDS = frozenset(
    {
        "full_name",
        "employee_code",
        "department",
        "designation",
        "date_of_joining",
        "date_of_exit",
        "employment_status",
        "photo_document",
    }
)

# --- Resources --------------------------------------------------------------

RES_ADMIN_SITE = "admin_site"
RES_EMPLOYEE = "employee"
RES_EMPLOYEE_DOCUMENT = "employee_document"
RES_USER_ACCOUNT = "user_account"
RES_PASSWORD = "password"  # noqa: S105 — a resource name, not a credential
RES_ROLE_ASSIGNMENT = "role_assignment"
RES_TRANSITION_RULE = "transition_rule"
RES_AUDIT_LOG = "audit_log"
RES_CLIENT = "client"
RES_JOB_CARD = "job_card"
RES_JOB_LINE = "job_line"
RES_QUOTATION = "quotation"
RES_DOCUMENT = "document"
RES_JOB_NOTE = "job_note"
RES_SHEET_EXPORT = "sheet_export"

PERMISSION_DESCRIPTIONS: dict[tuple[str, str], str] = {
    (RES_ADMIN_SITE, "view"): "Sign in to the Django admin site",
    (RES_EMPLOYEE, "view"): "View employee records",
    (RES_EMPLOYEE, "create"): "Create employee records",
    (RES_EMPLOYEE, "edit"): "Edit employee records",
    (RES_EMPLOYEE, "delete"): "Delete employee records",
    (RES_EMPLOYEE_DOCUMENT, "view"): "View personal identity documents",
    (RES_USER_ACCOUNT, "view"): "View login accounts",
    (RES_USER_ACCOUNT, "create"): "Create login accounts",
    (RES_USER_ACCOUNT, "edit"): "Edit login accounts",
    (RES_PASSWORD, "edit"): "Change a password",
    (RES_ROLE_ASSIGNMENT, "create"): "Assign a role to a user",
    (RES_ROLE_ASSIGNMENT, "delete"): "Revoke a role from a user",
    (RES_TRANSITION_RULE, "view"): "View pipeline transition rules",
    (RES_TRANSITION_RULE, "edit"): "Edit pipeline transition rules",
    (RES_AUDIT_LOG, "view"): "Read the audit log",
    (RES_CLIENT, "view"): "View clients",
    (RES_CLIENT, "create"): "Create clients",
    (RES_CLIENT, "edit"): "Edit clients",
    (RES_JOB_CARD, "view"): "View job cards",
    (RES_JOB_CARD, "create"): "Create job cards",
    (RES_JOB_CARD, "edit"): "Edit job cards",
    (RES_JOB_CARD, "cancel"): "Cancel a job card",
    (RES_JOB_LINE, "view"): "View job lines",
    (RES_JOB_LINE, "create"): "Create job lines",
    (RES_JOB_LINE, "edit"): "Edit job lines",
    (RES_QUOTATION, "view"): "View quotations",
    (RES_QUOTATION, "create"): "Create quotation revisions",
    (RES_QUOTATION, "edit"): "Edit quotations",
    (RES_DOCUMENT, "create"): "Upload a file",
    (RES_JOB_NOTE, "create"): "Add a note to a job",
    (RES_SHEET_EXPORT, "view"): "Open the Google Sheets job card export",
}

# --- The grid ---------------------------------------------------------------
#
# Transcribed from BACKEND_PLAN.md Appendix B so the two can be read side by
# side. Cell values:
#
#   "y"     -> granted at level 0
#   "y(n)"  -> granted at level n
#   "own"   -> granted at level 0 with if_owner = TRUE
#   None    -> not granted
#
# Note the deliberate absence of any employee:edit grant for the operational
# roles. "Employees may change their own password and nothing else about their
# profile" is expressed as password:edit with if_owner, plus that absence —
# not as a special case in code.

def _row(*cells: str | None) -> dict[str, str | None]:
    """Pair nine cells with the nine role codes, in Appendix B's column order."""
    if len(cells) != len(ROLE_ORDER):
        raise ValueError(f"expected {len(ROLE_ORDER)} cells, got {len(cells)}")
    return dict(zip(ROLE_ORDER, cells, strict=True))


Y = "y"
OWN = "own"
Y1 = "y(1)"
Y2 = "y(2)"
_ = None

# fmt: off
GRID: dict[tuple[str, str], dict[str, str | None]] = {
    #                                        OWNER ADMIN HR    SALES DESIGN PROD  PURCH STORE ACCT
    (RES_ADMIN_SITE, "view"):        _row(Y,    Y,    Y,    _,    _,    _,    _,    _,    _),
    (RES_EMPLOYEE, "view"):          _row(Y1,   Y1,   Y1,   OWN,  OWN,  OWN,  OWN,  OWN,  OWN),
    (RES_EMPLOYEE, "create"):        _row(Y1,   Y1,   Y1,   _,    _,    _,    _,    _,    _),
    (RES_EMPLOYEE, "edit"):          _row(Y1,   Y1,   Y1,   _,    _,    _,    _,    _,    _),
    (RES_EMPLOYEE, "delete"):        _row(Y1,   Y1,   Y1,   _,    _,    _,    _,    _,    _),
    (RES_EMPLOYEE_DOCUMENT, "view"): _row(Y2,   _,    Y2,   _,    _,    _,    _,    _,    _),
    (RES_USER_ACCOUNT, "view"):      _row(Y,    Y,    Y,    _,    _,    _,    _,    _,    _),
    (RES_USER_ACCOUNT, "create"):    _row(Y,    Y,    Y,    _,    _,    _,    _,    _,    _),
    (RES_USER_ACCOUNT, "edit"):      _row(Y,    Y,    Y,    _,    _,    _,    _,    _,    _),
    (RES_PASSWORD, "edit"):          _row(OWN,  OWN,  OWN,  OWN,  OWN,  OWN,  OWN,  OWN,  OWN),
    (RES_ROLE_ASSIGNMENT, "create"): _row(Y,    Y,    _,    _,    _,    _,    _,    _,    _),
    (RES_ROLE_ASSIGNMENT, "delete"): _row(Y,    Y,    _,    _,    _,    _,    _,    _,    _),
    (RES_TRANSITION_RULE, "view"):   _row(Y,    Y,    _,    _,    _,    _,    _,    _,    _),
    (RES_TRANSITION_RULE, "edit"):   _row(Y,    Y,    _,    _,    _,    _,    _,    _,    _),
    (RES_AUDIT_LOG, "view"):         _row(Y,    Y,    _,    _,    _,    _,    _,    _,    _),
    (RES_CLIENT, "view"):            _row(Y,    Y,    _,    Y,    _,    _,    Y,    _,    Y),
    (RES_CLIENT, "create"):          _row(Y,    Y,    Y,    Y,    _,    _,    _,    _,    _),
    (RES_CLIENT, "edit"):            _row(Y,    _,    _,    Y,    _,    _,    _,    _,    _),
    (RES_JOB_CARD, "view"):          _row(Y,    Y,    _,    OWN,  Y,    Y,    Y,    Y,    Y),
    (RES_JOB_CARD, "create"):        _row(Y,    _,    _,    Y,    _,    _,    _,    _,    _),
    (RES_JOB_CARD, "edit"):          _row(Y,    _,    _,    Y,    _,    _,    _,    _,    _),
    (RES_JOB_CARD, "cancel"):        _row(Y,    _,    _,    Y,    _,    _,    _,    _,    _),
    (RES_JOB_LINE, "view"):          _row(Y,    Y,    _,    OWN,  Y,    Y,    Y,    Y,    Y),
    (RES_JOB_LINE, "create"):        _row(Y,    _,    _,    Y,    _,    _,    _,    _,    _),
    (RES_JOB_LINE, "edit"):          _row(Y,    _,    _,    Y,    _,    _,    _,    _,    _),
    (RES_QUOTATION, "view"):         _row(Y,    Y,    _,    Y,    _,    _,    _,    _,    Y),
    (RES_QUOTATION, "create"):       _row(Y,    _,    _,    _,    _,    _,    _,    _,    Y),
    (RES_QUOTATION, "edit"):         _row(Y,    _,    _,    Y,    _,    _,    _,    _,    _),
    (RES_DOCUMENT, "create"):        _row(Y,    Y,    Y,    Y,    Y,    Y,    Y,    Y,    Y),
    (RES_JOB_NOTE, "create"):        _row(Y,    Y,    _,    Y,    Y,    Y,    Y,    Y,    Y),
    (RES_SHEET_EXPORT, "view"):      _row(Y,    _,    _,    _,    _,    _,    _,    _,    Y),
}
# fmt: on


def parse_cell(cell: str | None) -> tuple[int, bool] | None:
    """Turn a grid cell into ``(perm_level, if_owner)``, or None if not granted."""
    if cell is None:
        return None
    if cell == OWN:
        return (LEVEL_ORDINARY, True)
    if cell == Y:
        return (LEVEL_ORDINARY, False)
    if cell.startswith("y(") and cell.endswith(")"):
        return (int(cell[2:-1]), False)
    raise ValueError(f"unrecognised grid cell {cell!r}")


def iter_grants():
    """Yield ``(resource, action, role_code, perm_level, if_owner)`` for the whole grid."""
    for (resource, action), row in GRID.items():
        for role_code, cell in row.items():
            parsed = parse_cell(cell)
            if parsed is None:
                continue
            perm_level, if_owner = parsed
            yield resource, action, role_code, perm_level, if_owner


def iter_permissions():
    """Yield the distinct ``(resource, action)`` pairs the grid references."""
    yield from GRID.keys()
