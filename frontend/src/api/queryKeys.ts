/**
 * One place for cache keys, because a transition has to invalidate the board, the card
 * and the line together — and a typo in a key is a stale board that nobody notices.
 */
/** Any bag of filter values; the object itself is the cache key. */
export type QueryFilters = Record<string, string | undefined>;

export const queryKeys = {
  me: ["me"] as const,
  enums: ["enums"] as const,
  stages: ["stages"] as const,
  productCategories: ["product-categories"] as const,

  dashboard: ["dashboard"] as const,

  board: (filters: QueryFilters) => ["board", filters] as const,

  clients: (filters: QueryFilters) => ["clients", filters] as const,
  client: (id: string) => ["client", id] as const,

  jobCards: (filters: QueryFilters) => ["job-cards", filters] as const,
  jobCard: (id: string) => ["job-card", id] as const,
  jobCardNotes: (id: string) => ["job-card", id, "notes"] as const,
  jobCardAttachments: (id: string) => ["job-card", id, "attachments"] as const,
  jobCardQuotations: (id: string) => ["job-card", id, "quotations"] as const,

  jobLine: (id: string) => ["job-line", id] as const,
};

/** Everything a completed transition can have changed. */
export const AFFECTED_BY_TRANSITION = ["board", "job-card", "job-line", "dashboard"] as const;
