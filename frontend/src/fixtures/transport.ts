/**
 * An in-memory stand-in for /api/v1, used when VITE_API_MODE=fixtures and by the component
 * tests. It answers the same paths with the same shapes as the real backend (see
 * backend/apps/sales/api.py and backend/apps/pipeline/api.py), and it holds state for the
 * length of a page load, so a transition really does move a line between board columns.
 *
 * It is not a second implementation of the domain: the rules it applies (what the next
 * stage is, which actions exist) are the fixtures' own, deliberately simple, and no screen
 * depends on them being right — the screens render whatever `available_actions` says.
 */

import { ApiError } from "@/api/client";
import type {
  ActionOption,
  Attachment,
  Board,
  ClientDetail,
  Contact,
  Dashboard,
  JobCardDetail,
  JobCardSummary,
  JobLine,
  JobLineDetail,
  JobLineSummary,
  Note,
  Quotation,
  Stage,
  StageRef,
  TransitionEvent,
} from "@/api/types";
import {
  type FixtureCard,
  type FixtureLine,
  type FixtureState,
  enums,
  initialState,
  me,
  productCategories,
  stages,
} from "./data";

let state: FixtureState = initialState();

/** Tests call this between cases; the dev server never does. */
export function resetFixtures(): void {
  state = initialState();
}

export function fixtureState(): FixtureState {
  return state;
}

const LATENCY_MS = import.meta.env.MODE === "test" ? 0 : 140;

function settle<T>(value: T): Promise<T> {
  if (LATENCY_MS === 0) return Promise.resolve(value);
  return new Promise((resolve) => setTimeout(() => resolve(value), LATENCY_MS));
}

function notFound(what: string): never {
  throw new ApiError(404, "not_found", `${what} not found`);
}

function id(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

/* ------------------------------------------------------------------ selectors */

function stageById(stageId: string): Stage {
  const stage = stages.find((candidate) => candidate.id === stageId) ?? stages[0];
  if (!stage) throw new Error("fixture stages are empty");
  return stage;
}

function stageRef(stageId: string): StageRef {
  const { id: stageId2, code, name } = stageById(stageId);
  return { id: stageId2, code, name };
}

function availableActions(line: FixtureLine): ActionOption[] {
  const current = stageById(line.current_stage_id);
  if (current.is_terminal) return [];

  const next = stages
    .filter((stage) => !stage.is_terminal && stage.sequence_no > current.sequence_no)
    .sort((a, b) => a.sequence_no - b.sequence_no)[0];
  const lost = stages.find((stage) => stage.code === "LOST");

  const actions: ActionOption[] = [];
  if (next) {
    actions.push({
      action_code: "advance",
      to_stage: stageRef(next.id),
      requires_note: false,
      available: true,
      blocked_by: null,
    });
  }
  if (lost) {
    actions.push({
      action_code: "mark_lost",
      to_stage: stageRef(lost.id),
      requires_note: true,
      available: true,
      blocked_by: null,
    });
  }
  return actions;
}

/** apps/sales/api.py::serialize_job_line — the plain shape. */
function toJobLine(line: FixtureLine): JobLine {
  return {
    id: line.id,
    line_no: line.line_no,
    product_category: line.product_category,
    description: line.description,
    quantity: line.quantity,
    line_status: line.line_status,
    required_by: line.required_by,
    specs: line.specs,
    current_stage: stageRef(line.current_stage_id),
  };
}

/** apps/pipeline/api.py::serialize_board_line — grouped-by-column shape, no current_stage. */
function toBoardLine(line: FixtureLine): JobLineSummary {
  return {
    id: line.id,
    line_no: line.line_no,
    description: line.description,
    quantity: line.quantity,
    line_status: line.line_status,
    required_by: line.required_by,
    product_category: line.product_category,
    job_card: {
      id: line.job_card_id,
      job_no: line.job_no,
      client: line.client,
      dispatch_policy: line.dispatch_policy,
    },
    available_actions: availableActions(line),
    // The fixture data models quotations per job card only, not per job line
    // (no QuotationLine equivalent) — see apps/sales/selectors.py::
    // latest_quotation_by_line for the real per-line join.
    quotation: null,
  };
}

/** apps/pipeline/api.py::job_line_detail — board-line shape plus full Stage, specs, history. */
function toLineDetail(line: FixtureLine): JobLineDetail {
  return {
    ...toBoardLine(line),
    current_stage: stageById(line.current_stage_id),
    specs: line.specs,
    history: (state.transitions[line.id] ?? []).map((event) => ({ ...event })),
  };
}

function linesOf(cardId: string): FixtureLine[] {
  return state.lines.filter((line) => line.job_card_id === cardId);
}

function toCardSummary(card: FixtureCard): JobCardSummary {
  return { ...card };
}

function toCardDetail(card: FixtureCard): JobCardDetail {
  const current = state.quotations
    .filter((quotation) => quotation.job_card_id === card.id)
    .find((quotation) => ["active", "sent"].includes(quotation.status));
  return {
    ...toCardSummary(card),
    lines: linesOf(card.id).map(toJobLine),
    quotations: state.quotations
      .filter((quotation) => quotation.job_card_id === card.id)
      .map(({ job_card_id: _jc, ...quotation }) => quotation),
    current_quotation_id: current?.id ?? null,
  };
}

function paginate<T>(rows: T[], params: URLSearchParams) {
  const size = Math.min(Number(params.get("page_size") ?? 50), 200);
  const number = Math.max(Number(params.get("page") ?? 1), 1);
  const start = (number - 1) * size;
  return {
    items: rows.slice(start, start + size),
    page: number,
    page_size: size,
    total: rows.length,
    pages: Math.max(Math.ceil(rows.length / size), 1),
  };
}

function matchesQuery(haystack: (string | null | undefined)[], needle: string | null): boolean {
  if (!needle) return true;
  const lowered = needle.toLowerCase();
  return haystack.some((value) => (value ?? "").toLowerCase().includes(lowered));
}

/* ------------------------------------------------------------------- handlers */

function formValue(body: unknown, key: string): string {
  if (body instanceof FormData) {
    const value = body.get(key);
    if (typeof value === "string") return value;
    if (value instanceof File) return value.name;
  }
  return "";
}

function jsonBody(body: unknown): Record<string, unknown> {
  return (body ?? {}) as Record<string, unknown>;
}

function applyTransition(lineId: string, body: unknown) {
  const line = state.lines.find((candidate) => candidate.id === lineId);
  if (!line) notFound("Job line");

  const payload = jsonBody(body);
  const actionCode = String(payload.action_code ?? "");
  const note = typeof payload.note === "string" ? payload.note : null;

  const action = availableActions(line).find((candidate) => candidate.action_code === actionCode);
  if (!action || !action.to_stage) {
    throw new ApiError(422, "rule_violation", "That move is not available from this stage.");
  }
  if (action.requires_note && !note) {
    throw new ApiError(422, "rule_violation", "This move needs a note.", {
      note: ["A note is required."],
    });
  }

  const fromCode = stageById(line.current_stage_id).code;
  const nextId = (Object.values(state.transitions).flat().length || 0) + 1;
  const event: TransitionEvent = {
    id: nextId,
    from_stage: fromCode,
    to_stage: action.to_stage.code,
    action_code: action.action_code,
    performed_by: me.username,
    performed_at: new Date().toISOString(),
    note,
  };

  line.current_stage_id = action.to_stage.id;
  state.transitions[line.id] = [...(state.transitions[line.id] ?? []), event];

  return {
    id: event.id,
    job_line_id: line.id,
    from_stage: event.from_stage,
    to_stage: event.to_stage,
    action_code: event.action_code,
    performed_at: event.performed_at,
    note: event.note,
    current_stage: stageById(line.current_stage_id),
    available_actions: availableActions(line),
  };
}

function board(params: URLSearchParams): Board {
  const ownerId = params.get("owner_user_id");

  const lines = state.lines.filter((line) => {
    if (ownerId) {
      const card = state.cards.find((candidate) => candidate.id === line.job_card_id);
      if (card?.owner_user.id !== ownerId) return false;
    }
    return matchesQuery([line.description, line.job_no, line.client], params.get("q"));
  });

  const columns = [...stages]
    .sort((a, b) => a.sequence_no - b.sequence_no)
    .map((stage) => ({
      stage,
      lines: lines.filter((line) => line.current_stage_id === stage.id).map(toBoardLine),
    }));

  return { module_code: "sales_pipeline", columns, total_lines: lines.length };
}

function dashboard(): Dashboard {
  const myCards = state.cards.filter((card) => card.owner_user.id === me.id);
  const myOpenCards = myCards.filter((card) =>
    ["open", "quoted", "rework"].includes(card.lifecycle_status),
  );

  const awaiting = state.lines
    .map((line) => ({ line, actions: availableActions(line) }))
    .filter(({ actions }) => actions.length > 0)
    .map(({ line, actions }) => ({
      ...toBoardLine(line),
      available_actions: actions,
      current_stage: stageRef(line.current_stage_id),
    }));

  const activity = Object.values(state.transitions)
    .flat()
    .sort((a, b) => new Date(b.performed_at).getTime() - new Date(a.performed_at).getTime())
    .slice(0, 20);

  return {
    my_open_job_cards: myOpenCards.map((card) => ({
      ...toCardSummary(card),
      line_count: linesOf(card.id).length,
      open_line_count: linesOf(card.id).filter((line) => line.line_status === "active").length,
    })),
    lines_awaiting_me: awaiting,
    recent_activity: activity,
  };
}

function createJobCard(body: unknown): JobCardSummary {
  const payload = jsonBody(body);
  const client = state.clients.find((candidate) => candidate.id === payload.client_id);
  if (!client) throw new ApiError(422, "rule_violation", "Choose a client.");

  const number = state.cards.length + 1;
  const cardId = id("jc");
  const jobNo = `JOB-2026-${String(number).padStart(4, "0")}`;
  const contact =
    client.contacts.find((candidate) => candidate.id === payload.client_contact) ?? null;

  const card: FixtureCard = {
    id: cardId,
    job_no: jobNo,
    client: { id: client.id, client_code: client.client_code, legal_name: client.legal_name },
    client_contact: contact,
    owner_user: { id: me.id, username: me.username },
    lifecycle_status: "open",
    enquiry_source: String(payload.enquiry_source ?? "other"),
    dispatch_policy: String(payload.dispatch_policy ?? client.default_dispatch_policy),
    enquiry_date: String(payload.enquiry_date ?? new Date().toISOString().slice(0, 10)),
    required_by: (payload.required_by as string | null) ?? null,
    requirements: (payload.requirements as Record<string, string>) ?? {},
  };

  state.cards = [card, ...state.cards];
  state.notes[cardId] = [];
  state.attachments[cardId] = [];

  return toCardSummary(card);
}

function addJobLine(cardId: string, body: unknown): JobLine {
  const card = state.cards.find((candidate) => candidate.id === cardId);
  if (!card) notFound("Job card");
  const initial = stages.find((stage) => stage.is_initial) ?? stages[0];
  if (!initial) throw new ApiError(500, "configuration_error", "No initial stage.");

  const payload = jsonBody(body);
  const category = productCategories.find(
    (candidate) => candidate.id === payload.product_category_id,
  );
  if (!category) throw new ApiError(422, "rule_violation", "Choose a product category.");

  const line: FixtureLine = {
    id: id("jl"),
    job_card_id: card.id,
    job_no: card.job_no,
    client: card.client.legal_name,
    dispatch_policy: card.dispatch_policy,
    line_no: linesOf(card.id).length + 1,
    description: String(payload.description ?? ""),
    product_category: category,
    quantity: Number(payload.quantity ?? 1),
    line_status: "active",
    required_by: (payload.required_by as string | null) ?? null,
    specs: (payload.specs as Record<string, string>) ?? {},
    current_stage_id: initial.id,
  };
  state.lines.push(line);
  return toJobLine(line);
}

function uploadRevision(cardId: string, body: unknown): Quotation {
  const existing = state.quotations.filter((quotation) => quotation.job_card_id === cardId);
  const current = existing.find((quotation) => quotation.status === "draft");
  const revisionNo = existing.length;
  const quotationId = id("q");

  const quotation: Quotation & { job_card_id: string } = {
    id: quotationId,
    job_card_id: cardId,
    quotation_no: `SR-Q-${cardId}`,
    revision_no: revisionNo,
    status: "draft",
    supersedes_id: current?.id ?? null,
    quoted_amount: formValue(body, "quoted_amount") || "0.00",
    currency: "INR",
    valid_till: formValue(body, "valid_till") || null,
    has_pdf: formValue(body, "pdf").length > 0,
    prepared_by: me.username,
  };

  if (current) {
    current.status = "superseded";
  }
  state.quotations.push(quotation);
  const { job_card_id: _jc, ...rest } = quotation;
  return rest;
}

/* -------------------------------------------------------------------- routing */

export async function handle(method: string, fullPath: string, body: unknown): Promise<unknown> {
  const [path, search = ""] = fullPath.split("?");
  const params = new URLSearchParams(search);
  const segments = (path ?? "").split("/").filter(Boolean);
  const [head, first, second, third] = segments;

  const route = `${method} /${head ?? ""}`;

  switch (route) {
    case "GET /me":
      return settle(me);
    case "GET /enums":
      return settle(enums);
    case "GET /product-categories":
      return settle({ items: productCategories });
    case "GET /dashboard":
      return settle(dashboard());
    case "GET /board":
      return settle(board(params));
    default:
      break;
  }

  if (route === "GET /pipeline" && first === "stages") {
    return settle({ module_code: "sales_pipeline", items: stages });
  }

  if (head === "clients") {
    if (method === "GET" && !first) {
      const rows = state.clients
        .filter((client) => (params.get("is_active") === "true" ? client.is_active : true))
        .filter((client) =>
          matchesQuery(
            [client.legal_name, client.client_code, client.billing_city],
            params.get("q"),
          ),
        );
      return settle(paginate(rows, params));
    }
    if (method === "POST" && !first) {
      const payload = jsonBody(body);
      // Mirrors apps.core.numbering.next_client_code() — client_code is never
      // caller-supplied, real or fixture.
      const clientCode = `CLI-${String(state.clients.length + 1).padStart(3, "0")}`;
      const client: ClientDetail = {
        id: id("cl"),
        client_code: clientCode,
        legal_name: String(payload.legal_name ?? ""),
        billing_city: (payload.billing_city as string) ?? null,
        billing_state: (payload.billing_state as string) ?? null,
        gstin: (payload.gstin as string) ?? null,
        is_active: true,
        default_dispatch_policy: (payload.default_dispatch_policy as string) ?? "partial_allowed",
        contacts: [],
      };
      state.clients = [client, ...state.clients];
      return settle(client);
    }
    if (first && !second) {
      const client = state.clients.find((candidate) => candidate.id === first);
      if (!client) notFound("Client");
      if (method === "PATCH") Object.assign(client, jsonBody(body));
      return settle(client);
    }
    if (first && second === "contacts" && method === "POST") {
      const client = state.clients.find((candidate) => candidate.id === first);
      if (!client) notFound("Client");
      const payload = jsonBody(body);
      const contact: Contact = {
        id: id("ct"),
        contact_name: String(payload.contact_name ?? ""),
        phone: (payload.phone as string) ?? null,
        email: (payload.email as string) ?? null,
        is_primary: Boolean(payload.is_primary),
      };
      // The service demotes the previous primary; the index alone would just reject this.
      if (contact.is_primary) {
        for (const existing of client.contacts) existing.is_primary = false;
      }
      client.contacts.push(contact);
      return settle(contact);
    }
  }

  if (head === "job-cards") {
    if (method === "GET" && !first) {
      const mine = params.get("mine") === "1";
      const status = params.get("status");
      const clientId = params.get("client_id");
      const rows = state.cards
        .filter((card) => (mine ? card.owner_user.id === me.id : true))
        .filter((card) => (status ? status.split(",").includes(card.lifecycle_status) : true))
        .filter((card) => (clientId ? card.client.id === clientId : true))
        .filter((card) => matchesQuery([card.job_no, card.client.legal_name], params.get("q")))
        .map(toCardSummary);
      return settle(paginate(rows, params));
    }
    if (method === "POST" && !first) {
      return settle(createJobCard(body));
    }
    if (first && !second) {
      const card = state.cards.find((candidate) => candidate.id === first);
      if (!card) notFound("Job card");
      if (method === "PATCH") Object.assign(card, jsonBody(body));
      return settle(toCardDetail(card));
    }
    if (first && second === "notes") {
      if (method === "GET") return settle({ items: state.notes[first] ?? [] });
      const note: Note = {
        id: id("n"),
        body: String(jsonBody(body).body ?? ""),
        author: me.username,
        job_line_id: null,
        created_at: new Date().toISOString(),
      };
      state.notes[first] = [note, ...(state.notes[first] ?? [])];
      return settle(note);
    }
    if (first && second === "attachments") {
      if (method === "GET") return settle({ items: state.attachments[first] ?? [] });
      if (method === "DELETE" && third) {
        state.attachments[first] = (state.attachments[first] ?? []).filter(
          (attachment) => attachment.id !== third,
        );
        return settle(undefined);
      }
      const file = body instanceof FormData ? body.get("file") : null;
      const attachment: Attachment = {
        id: id("at"),
        label: body instanceof FormData ? (body.get("label") as string | null) : null,
        filename: file instanceof File ? file.name : "upload.bin",
        mime_type: file instanceof File ? file.type : "application/octet-stream",
        byte_size: file instanceof File ? file.size : 0,
        job_line_id: null,
        attached_by: me.username,
        attached_at: new Date().toISOString(),
      };
      state.attachments[first] = [attachment, ...(state.attachments[first] ?? [])];
      return settle(attachment);
    }
    if (first && second === "quotations") {
      if (method === "GET") {
        return settle({
          items: state.quotations
            .filter((quotation) => quotation.job_card_id === first)
            .map(({ job_card_id: _jc, ...quotation }) => quotation),
        });
      }
      return settle(uploadRevision(first, body));
    }
    if (first && second === "lines" && method === "POST") {
      return settle(addJobLine(first, body));
    }
  }

  if (head === "job-lines" && first) {
    if (second === "transitions" && method === "POST") {
      return settle(applyTransition(first, body));
    }
    if (second === "edit" && method === "PATCH") {
      const line = state.lines.find((candidate) => candidate.id === first);
      if (!line) notFound("Job line");
      Object.assign(line, jsonBody(body));
      return settle(toJobLine(line));
    }
    if (!second) {
      const line = state.lines.find((candidate) => candidate.id === first);
      if (!line) notFound("Job line");
      return settle(toLineDetail(line));
    }
  }

  throw new ApiError(404, "not_found", `No fixture route for ${method} ${path}`);
}
