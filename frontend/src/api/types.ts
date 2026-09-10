/**
 * Wire types for /api/v1. These mirror the real, hand-written Django views in
 * apps/*\/api.py and are pinned there by contract tests
 * (backend/tests/contract/*.py), because without DRF there is no schema to
 * generate from. Change one side, change the other in the same commit.
 *
 * Rules that hold across every payload:
 *   - ids are UUID strings, except TransitionEvent.id (a BigAutoField, so a number)
 *   - money is a decimal *string*, never a number (FRONTEND_PLAN.md guardrail 4)
 *   - timestamps are ISO-8601 UTC; plain dates are YYYY-MM-DD
 *   - responses are objects, never bare arrays
 */

/** apps/core/api.py::paginate() — one shape for every paginated endpoint. */
export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; fields?: Record<string, string[]> };
}

/* ------------------------------------------------------------------ identity */

/**
 * A resolved grant. The server sends these rather than role codes so the client never
 * has to know which role implies what — see auth/can.ts for the evaluation rules.
 * `level` is a field-sensitivity threshold (0 = ordinary, 1 = protected, 2 = sensitive —
 * apps/identity/constants.py LEVEL_*), not a scope: it's about which *fields* a grant
 * reaches, orthogonal to `if_owner`, which is the all-vs-own scope axis.
 */
export interface GrantEntry {
  resource: string;
  action: string;
  level: number;
  if_owner: boolean;
}

export interface Role {
  code: string;
  name: string;
}

/** apps/identity/api.py::serialize_me — pinned exactly by
 * backend/tests/contract/test_session_api.py::test_me_payload_keys_are_exactly_this. */
export interface Me {
  id: string;
  username: string;
  full_name: string;
  employee_id: string;
  employee_code: string;
  department: string;
  must_change_password: boolean;
  last_login: string | null;
  roles: Role[];
  /** Only present with sheet_export:view (Owner, Accounts) — the sidebar's
   * link to the Google Sheets job card ledger. null when not permitted, or
   * when the sync hasn't been configured with a spreadsheet yet. */
  sheet_export_url: string | null;
  grants: GrantEntry[];
}

/* ----------------------------------------------------------------- reference */

export interface EnumChoice {
  value: string;
  label: string;
}

/** apps/core/enums_api.py — flat, keyed by domain name directly (job_lifecycle_status,
 * job_line_status, quotation_status, dispatch_policy, enquiry_source, employment_status,
 * employee_document_type, permission_action, audit_operation). No "quotation_outcome"
 * domain exists — that outcome is a plain boolean, not an enum (see QuotationPanel). */
export type Enums = Record<string, EnumChoice[]>;

/** apps/pipeline/api.py::serialize_stage */
export interface Stage {
  id: string;
  code: string;
  name: string;
  module_code: string;
  sequence_no: number;
  department: string | null;
  is_initial: boolean;
  is_terminal: boolean;
}

export interface ProductCategory {
  id: string;
  code: string;
  name: string;
  is_manufactured: boolean;
}

/* ------------------------------------------------------------------- clients */

/** apps/sales/api.py::serialize_contact */
export interface Contact {
  id: string;
  contact_name: string;
  phone: string | null;
  email: string | null;
  is_primary: boolean;
}

/** apps/sales/api.py::serialize_client */
export interface ClientSummary {
  id: string;
  client_code: string;
  legal_name: string;
  gstin: string | null;
  billing_city: string | null;
  billing_state: string | null;
  default_dispatch_policy: string;
  is_active: boolean;
}

/** apps/sales/api.py::client_detail (GET) — serialize_client plus contacts. */
export interface ClientDetail extends ClientSummary {
  contacts: Contact[];
}

/* ------------------------------------------------------------- pipeline bits */

/** A light stage reference — apps/sales/api.py::serialize_job_line's
 * current_stage, and apps/pipeline/api.py::_serialise_action's to_stage.
 * Distinct from the full Stage above (no module_code/sequence_no/etc). */
export interface StageRef {
  id: string;
  code: string;
  name: string;
  /** Only present where the server actually sends it (current_stage, to_stage on an
   * action) — absent on the synthetic StageRef StageTimeline builds from a history
   * entry's bare code, which never carries this. Treat undefined as "not terminal". */
  is_terminal?: boolean;
  /** Mirrors apps.sales.models.JobLifecycleStatus ("won" | "lost" | "cancelled" | ...),
   * or null when this stage carries no card-level outcome. Same presence caveat as
   * is_terminal above — only sent on to_stage. Distinguishes a routine outcome (lost)
   * from an administrative override (cancelled); both are terminal, only one is a
   * kill switch. */
  cascades_job_card_status?: string | null;
}

/** apps/pipeline/api.py::_serialise_action — one entry of `available_actions`,
 * built from pipeline_transition_rules joined against the user's active
 * roles, which is why the client never computes a next stage for itself. */
export interface ActionOption {
  action_code: string;
  to_stage: StageRef | null;
  requires_note: boolean;
  /** Whether the actor could take this action right now. */
  available: boolean;
  /** Why not, when `available` is false (e.g. "self_approval", "condition") — reported,
   * not hidden, so a greyed-out button can explain itself. Null when available. */
  blocked_by: string | null;
}

/** One entry of a job line's transition history — apps/pipeline/api.py::
 * job_line_detail's `history`. from_stage/to_stage are plain stage-code
 * strings here, not StageRef objects — deliberately different from
 * ActionOption.to_stage, which is a real object. */
export interface TransitionEvent {
  id: number;
  from_stage: string | null;
  to_stage: string;
  action_code: string;
  performed_by: string;
  performed_at: string;
  note: string | null;
}

/* ----------------------------------------------------------------- job cards */

/** apps/sales/api.py::serialize_job_card */
export interface JobCardSummary {
  id: string;
  job_no: string;
  client: { id: string; client_code: string; legal_name: string };
  client_contact: Contact | null;
  owner_user: { id: string; username: string };
  lifecycle_status: string;
  enquiry_source: string;
  dispatch_policy: string;
  enquiry_date: string;
  required_by: string | null;
  requirements: Record<string, string>;
}

/** apps/sales/api.py::job_card_detail (GET) */
export interface JobCardDetail extends JobCardSummary {
  lines: JobLine[];
  quotations: Quotation[];
  current_quotation_id: string | null;
}

/** apps/sales/api.py::serialize_job_line — the plain shape from
 * GET/POST job-cards/{id}/lines. Distinct from the board/detail shapes below,
 * which carry different extra context (see JobLineSummary / JobLineDetail). */
export interface JobLine {
  id: string;
  line_no: number;
  product_category: ProductCategory;
  description: string;
  quantity: number;
  line_status: string;
  required_by: string | null;
  specs: Record<string, string>;
  current_stage: StageRef;
}

/** apps/pipeline/api.py::serialize_board_line — one line as it appears on the
 * board, grouped under its stage's column. No current_stage: the column it's
 * grouped under already says that. `job_card.client` is the client's legal
 * name as a plain string, not an object — the board doesn't need more. */
export interface JobLineSummary {
  id: string;
  line_no: number;
  description: string;
  quantity: number;
  line_status: string;
  required_by: string | null;
  /** When the line entered its current stage — its latest transition's performed_at.
   * Null on the job-line detail payload (which reuses this same shape but doesn't need
   * a redundant stat next to its own full history); always present on the board. */
  stage_entered_at: string | null;
  product_category: ProductCategory;
  job_card: { id: string; job_no: string; client: string; dispatch_policy: string };
  available_actions: ActionOption[];
  /** The latest quotation revision that actually prices this line — apps/sales/
   * selectors.py::latest_quotation_by_line. Null both when no quotation exists yet
   * and when the viewer lacks quotation:view (the board is open to more roles than
   * quotations are). */
  quotation: { quotation_no: string; revision_no: number; status: string } | null;
}

/** apps/pipeline/api.py::job_line_detail — the board-line shape plus the full
 * Stage (not StageRef), specs, and transition history. */
export interface JobLineDetail extends JobLineSummary {
  current_stage: Stage;
  specs: Record<string, string>;
  history: TransitionEvent[];
}

/** apps/sales/api.py::serialize_note */
export interface Note {
  id: string;
  body: string;
  author: string;
  job_line_id: string | null;
  created_at: string;
}

/** apps/sales/api.py::serialize_attachment */
export interface Attachment {
  id: string;
  label: string | null;
  filename: string;
  mime_type: string;
  byte_size: number;
  job_line_id: string | null;
  attached_by: string;
  attached_at: string;
}

/* ---------------------------------------------------------------- quotations */

/** apps/sales/api.py::serialize_quotation */
export interface Quotation {
  id: string;
  quotation_no: string;
  revision_no: number;
  status: string;
  supersedes_id: string | null;
  quoted_amount: string | null;
  currency: string;
  valid_till: string | null;
  has_pdf: boolean;
  prepared_by: string;
}

/** apps/pipeline/api.py::create_transition — its own shape, not a JobLine or
 * JobLineDetail: no line_no/description/quantity/job_card, just the move
 * itself plus the line's new state. */
export interface TransitionResult {
  id: number;
  job_line_id: string;
  from_stage: string | null;
  to_stage: string;
  action_code: string;
  performed_at: string;
  note: string | null;
  current_stage: Stage;
  available_actions: ActionOption[];
}

/* --------------------------------------------------------------------- board */

/** apps/pipeline/api.py::board() */
export interface Board {
  module_code: string;
  columns: { stage: Stage; lines: JobLineSummary[] }[];
  total_lines: number;
}

/* ----------------------------------------------------------------- dashboard */

/** apps/sales/api.py::dashboard() */
export interface Dashboard {
  my_open_job_cards: (JobCardSummary & { line_count: number; open_line_count: number })[];
  /** Board lines, but flat rather than grouped by column — so each one carries
   * its current_stage explicitly, unlike a plain JobLineSummary. */
  lines_awaiting_me: (JobLineSummary & { current_stage: StageRef })[];
  recent_activity: TransitionEvent[];
}
