/**
 * The client half of the permission grid.
 *
 * This mirrors `identity.services.has_permission` on the server. The mirror exists only to
 * decide what to *render*: every endpoint re-checks, and the 403 is the enforcement
 * (FRONTEND_PLAN.md guardrail 2). A hidden button is a convenience, never a control.
 *
 * Evaluation rules, matching `has_permission` exactly:
 *   1. Grants are matched on (resource, action). `*` matches any resource or any action,
 *      so an administrator grant is one row rather than one row per screen.
 *   2. There is no explicit-denial level — permission exists purely because a matching
 *      grant row exists. `level` (0/1/2) is a field-sensitivity threshold, not a scope;
 *      the client has no notion of "level" to ask for (it never edits protected/sensitive
 *      employee fields directly), so every check here is implicitly level 0, which every
 *      grant satisfies (`grant.level >= 0`).
 *   3. `if_owner: false` permits outright — an unrestricted grant.
 *   4. `if_owner: true` requires an object, and requires it to belong to the user
 *      (`obj.owner_user_id === grants.user_id`). With no object supplied (a nav item, a
 *      "New enquiry" button) it still permits: the user is asking whether the action
 *      exists for them at all, and the server checks the real object when one exists.
 */

import type { GrantEntry, Me } from "@/api/types";

export const ANY = "*";

export interface Grants {
  user_id: string;
  entries: GrantEntry[];
}

/** Anything with an owner. Job cards, job lines and quotations all carry `owner_user_id`. */
export interface OwnedObject {
  owner_user_id?: string | null;
}

export function grantsFrom(me: Me): Grants {
  return { user_id: me.id, entries: me.grants };
}

export const EMPTY_GRANTS: Grants = { user_id: "", entries: [] };

function matches(grant: GrantEntry, resource: string, action: string): boolean {
  return (
    (grant.resource === resource || grant.resource === ANY) &&
    (grant.action === action || grant.action === ANY)
  );
}

export function can(
  grants: Grants,
  resource: string,
  action: string,
  obj?: OwnedObject | null,
): boolean {
  for (const grant of grants.entries) {
    if (!matches(grant, resource, action)) continue;
    if (!grant.if_owner) return true;
    if (!obj) return true; // rule 4: no object yet, server checks the real one
    if (obj.owner_user_id && obj.owner_user_id === grants.user_id) return true;
  }

  return false;
}

/** `can` for a list of (resource, action) pairs — true when any one of them passes. */
export function canAny(
  grants: Grants,
  pairs: [resource: string, action: string][],
  obj?: OwnedObject | null,
): boolean {
  return pairs.some(([resource, action]) => can(grants, resource, action, obj));
}
