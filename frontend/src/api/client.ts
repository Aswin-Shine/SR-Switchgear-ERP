import type { ApiErrorBody } from "./types";

const API_ROOT = "/api/v1";
const LOGIN_PATH = "/login/";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * Fixture transport: with VITE_API_MODE=fixtures the app runs with no Django behind it
 * (FE0 in the plan). The import is dynamic so the fixture data lands in its own chunk
 * that a production build never fetches.
 */
const FIXTURE_MODE = import.meta.env.VITE_API_MODE === "fixtures";
type FixtureHandler = (method: string, path: string, body: unknown) => Promise<unknown>;
let fixtureHandler: Promise<FixtureHandler> | null = null;

function loadFixtureHandler(): Promise<FixtureHandler> {
  if (!fixtureHandler) {
    fixtureHandler = import("../fixtures/transport").then((m) => m.handle);
  }
  return fixtureHandler;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: Record<string, string[]>;

  constructor(
    status: number,
    code: string,
    message: string,
    fields: Record<string, string[]> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }

  /** The line moved under us. apply_transition()'s row lock did its job. */
  get isStale(): boolean {
    return this.status === 409;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  /** A rule said no (DomainError/RuleViolation), as opposed to a malformed request. */
  get isRuleViolation(): boolean {
    return this.status === 422;
  }

  /** Flattened field errors, for forms that show one line per field. */
  fieldMessages(): [string, string][] {
    return Object.entries(this.fields).flatMap(([field, messages]) =>
      messages.map((message) => [field, message] as [string, string]),
    );
  }
}

/**
 * CSRF_COOKIE_HTTPONLY is True, so the token comes from the meta tag Django injects when
 * it renders index.html. Under `vite dev` the tag still holds the literal template tag;
 * treat that as absent and let the dev proxy forward the real cookie.
 */
export function csrfToken(): string | null {
  const content = document
    .querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
    ?.content?.trim();
  if (!content || content.includes("{{")) return null;
  return content;
}

/** The bootstrap blob Django inlines. Absent (and unparseable) under `vite dev`. */
export function bootstrap<T = Record<string, unknown>>(): T | null {
  const raw = document.getElementById("bootstrap")?.textContent;
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

/** Where a 401 sends the browser. Django owns login, so this leaves the SPA entirely. */
export function loginUrlFor(pathname: string, search: string): string {
  return `${LOGIN_PATH}?next=${encodeURIComponent(`${pathname}${search}`)}`;
}

function redirectToLogin(): void {
  window.location.assign(loginUrlFor(window.location.pathname, window.location.search));
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `Request failed (${response.status})`;
  let fields: Record<string, string[]> = {};
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      fields = body.error.fields ?? {};
    }
  } catch {
    // A non-JSON error body (a proxy page, a 500 rendered by Django) keeps the default.
  }
  return new ApiError(response.status, code, message, fields);
}

export interface RequestOptions {
  method?: string;
  /** JSON body. Mutually exclusive with `form`. */
  body?: unknown;
  /** Multipart body, for attachment and quotation uploads. */
  form?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

function buildPath(path: string, query: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const fullPath = buildPath(path, options.query);

  if (FIXTURE_MODE) {
    const handle = await loadFixtureHandler();
    return (await handle(method, fullPath, options.form ?? options.body)) as T;
  }

  const headers: Record<string, string> = { Accept: "application/json" };
  if (UNSAFE.has(method)) {
    const token = csrfToken();
    if (token) headers["X-CSRFToken"] = token;
  }

  let payload: BodyInit | undefined;
  if (options.form) {
    payload = options.form; // fetch sets the multipart boundary itself
  } else if (options.body !== undefined) {
    payload = JSON.stringify(options.body);
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_ROOT}${fullPath}`, {
    method,
    headers,
    body: payload,
    credentials: "same-origin",
    signal: options.signal,
    redirect: "manual", // a 302 to /login/ must not be followed and parsed as JSON
  });

  if (response.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "not_authenticated", "Your session has ended. Signing you in again.");
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) =>
    request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", form }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
