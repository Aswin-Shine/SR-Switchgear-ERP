/**
 * The resource and action vocabulary used with `can()`. It lives here so a screen never
 * carries a bare string, and so renaming a resource is one edit. These are permission
 * names, not pipeline action codes — a line's moves come from `available_actions`.
 *
 * Pinned exactly against apps/identity/constants.py::PERMISSION_DESCRIPTIONS — every
 * (resource, action) pair below is one the server actually grants. There is no separate
 * "contact" resource (contacts are governed by client:edit), no "attachment" resource
 * (it's "document"), no "note" resource (it's "job_note"), and no "board" resource
 * (board visibility is job_line:view — the board is a view of job lines, not its own
 * permission). "print"/"transition"/"send"/"upload" are not real actions either.
 */
export const RESOURCE = {
  client: "client",
  jobCard: "job_card",
  jobLine: "job_line",
  quotation: "quotation",
  document: "document",
  jobNote: "job_note",
  adminSite: "admin_site",
  sheetExport: "sheet_export",
} as const;

export const ACTION = {
  view: "view",
  create: "create",
  edit: "edit",
  cancel: "cancel",
} as const;

export type Resource = (typeof RESOURCE)[keyof typeof RESOURCE];
export type Action = (typeof ACTION)[keyof typeof ACTION];
