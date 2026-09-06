# Shared test fixtures

## `permission_cases.json`

One case table, two implementations. `pytest` runs it against
`identity.services.has_permission`; `vitest` runs it against `frontend/src/auth/can.ts`
(see `frontend/src/auth/can.test.ts`). The permission grid is expressed twice — enforced on
the server, mirrored in the client to decide what to render — and this file is what keeps
the two from drifting apart quietly.

**Add a case here before changing either implementation.** A rule that only one side knows
about is the failure this file exists to prevent.

### Shape

```json
{
  "name": "human-readable description of the rule under test",
  "user_id": "the acting user",
  "grants": [{ "resource": "job_card", "action": "edit", "perm_level": "own", "if_owner": true }],
  "resource": "job_card",
  "action": "edit",
  "object": { "owner_user_id": "u-sales" },
  "expected": true
}
```

`object` is `null` when the question is about the action in general rather than a specific
row — a nav item, a "New enquiry" button.

### The rules both implementations must follow

1. Grants match on `(resource, action)`. `*` matches any resource or any action, so an
   administrator is one row rather than one row per screen.
2. A matching grant with `perm_level: "none"` is an explicit denial and wins outright,
   whatever else the user holds, and regardless of the order grants arrive in.
3. Otherwise the widest surviving grant decides. `if_owner: true` narrows a grant to
   objects the user owns whatever its `perm_level`, so the effective scope is `own` when
   `if_owner` is set and the grant's own `perm_level` otherwise.
4. Scope `all` permits. Scope `own` permits when `object.owner_user_id` equals `user_id`;
   an object with no owner never satisfies an owner-scoped grant.
5. With no object, an `own` grant permits: the user is asking whether the action exists for
   them at all, and the server checks the object when there is one.

### Suggested Python side

```python
import json, pathlib, pytest
from apps.identity.services import has_permission

CASES = json.loads((pathlib.Path(__file__).parents[1] / "fixtures" / "permission_cases.json").read_text())

@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_permission_case(case):
    assert has_permission(case["user_id"], case["grants"], case["resource"], case["action"], case["object"]) is case["expected"]
```

Adapt the call to whatever signature `has_permission` settles on; what matters is that both
suites read this file rather than each keeping their own copy of the table.
