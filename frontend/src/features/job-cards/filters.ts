/**
 * The list opens on "my active jobs", which is also the shape of idx_job_cards_open.
 *
 * `active` is not a real lifecycle_status value — it's a client-known filter meaning
 * "any of open/quoted/rework", matching apps.sales.selectors.OPEN_STATUSES exactly (the
 * same set the Dashboard's "My open job cards" already uses). It is named here — in a
 * .ts module, not in a screen — so it is one edit if the vocabulary ever changes.
 * Everything else about status comes from GET /api/v1/enums: the filter's other options,
 * and every label rendered. (Previously this defaulted to the literal `open` status
 * alone, which silently excluded `quoted`/`rework` cards the Dashboard already counted
 * as "open" — a real, reported inconsistency between the two screens.)
 */
/** URL-facing default. The API's own filter is `mine=1` (see api/endpoints/jobCards.ts) —
 * this stays "owner=me" in the URL so a shared/reloaded link keeps its shape, and the page
 * translates it right before calling useJobCards. */
export const DEFAULT_JOB_CARD_FILTERS = {
  owner: "me",
  status: "active",
} as const;

export const OWNER_ME = "me";
export const STATUS_ACTIVE = "active";
