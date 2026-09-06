/**
 * The list opens on "my open jobs", which is also the shape of idx_job_cards_open.
 *
 * `open` is the one status code the client names, and it is named here — in a .ts module,
 * not in a screen — so it is one edit if the vocabulary ever changes. Everything else about
 * status comes from GET /api/v1/enums: the filter's options, and every label rendered.
 */
/** URL-facing default. The API's own filter is `mine=1` (see api/endpoints/jobCards.ts) —
 * this stays "owner=me" in the URL so a shared/reloaded link keeps its shape, and the page
 * translates it right before calling useJobCards. */
export const DEFAULT_JOB_CARD_FILTERS = {
  owner: "me",
  status: "open",
} as const;

export const OWNER_ME = "me";
