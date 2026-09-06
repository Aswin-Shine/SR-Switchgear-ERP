import { ToastProvider } from "@/components/Toast";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type RenderResult, render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

/** Retries and background refetching turn test failures into timeouts. Off, both. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  options: { route?: string; queryClient?: QueryClient } = {},
): RenderResult & { queryClient: QueryClient } {
  const queryClient = options.queryClient ?? createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MemoryRouter initialEntries={[options.route ?? "/"]}>{children}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  }

  // Object.assign rather than a spread: RenderResult's query helpers are lost by a spread.
  return Object.assign(render(ui, { wrapper: Wrapper }), { queryClient });
}

export interface RouteContext {
  url: URL;
  method: string;
  body: unknown;
}

type RouteHandler = unknown | ((context: RouteContext) => unknown);

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function apiError(status: number, code: string, message: string): Response {
  return jsonResponse({ error: { code, message } }, status);
}

/**
 * A plain fetch stub keyed by "METHOD /path" — no msw, per the plan. Handlers return a
 * value (sent as 200 JSON) or a Response for anything else.
 */
export function mockFetch(routes: Record<string, RouteHandler>) {
  const calls: RouteContext[] = [];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const raw = init?.body;
    const body =
      typeof raw === "string"
        ? (JSON.parse(raw) as unknown)
        : raw instanceof FormData
          ? raw
          : undefined;

    calls.push({ url, method, body });

    const handler = routes[`${method} ${url.pathname}`];
    if (handler === undefined) {
      return apiError(404, "not_found", `No stub for ${method} ${url.pathname}`);
    }
    const value = typeof handler === "function" ? await handler({ url, method, body }) : handler;
    return value instanceof Response ? value : jsonResponse(value);
  });

  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}
