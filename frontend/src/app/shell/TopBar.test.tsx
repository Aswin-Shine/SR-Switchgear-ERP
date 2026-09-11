import type { GrantEntry, Me } from "@/api/types";
import { SessionProvider } from "@/auth/SessionProvider";
import { apiError, mockFetch, renderWithProviders } from "@/test/utils";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TopBar } from "./TopBar";

function me(grants: GrantEntry[]): Me {
  return {
    id: "u-1",
    username: "rmenon",
    full_name: "R Menon",
    employee_id: "e-1",
    employee_code: "SR-014",
    department: "Sales",
    must_change_password: false,
    last_login: null,
    roles: [{ code: "sales_exec", name: "Sales Executive" }],
    sheet_export_url: null,
    grants,
  };
}

const grant = (resource: string, action: string): GrantEntry => ({
  resource,
  action,
  level: 0,
  if_owner: false,
});

function renderTopBar(payload: Me, extra: Record<string, unknown> = {}) {
  const { calls } = mockFetch({ "GET /api/v1/me": payload, ...extra });
  const result = renderWithProviders(
    <SessionProvider>
      <TopBar />
    </SessionProvider>,
  );
  return { ...result, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TopBar", () => {
  it("offers the sync icon button only with a sheet_export:view grant", async () => {
    const { unmount } = renderTopBar(me([]));
    expect(await screen.findByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync job sheet" })).not.toBeInTheDocument();
    unmount();

    renderTopBar(me([grant("sheet_export", "view")]));
    expect(await screen.findByRole("button", { name: "Sync job sheet" })).toBeInTheDocument();
  });

  it("syncs the sheet and reports the result", async () => {
    const user = userEvent.setup();
    const { calls } = renderTopBar(me([grant("sheet_export", "view")]), {
      "POST /api/v1/sync-job-sheet": { synced: 3 },
    });

    await user.click(await screen.findByRole("button", { name: "Sync job sheet" }));

    expect(await screen.findByText("Synced 3 job cards.")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.url.pathname === "/api/v1/sync-job-sheet" && call.method === "POST",
        ),
      ).toBe(true);
    });
  });

  it("reports a sync failure", async () => {
    const user = userEvent.setup();
    renderTopBar(me([grant("sheet_export", "view")]), {
      "POST /api/v1/sync-job-sheet": apiError(
        502,
        "upstream_service_error",
        "Google Sheets sync failed",
      ),
    });

    await user.click(await screen.findByRole("button", { name: "Sync job sheet" }));

    expect(await screen.findByText("Google Sheets sync failed")).toBeInTheDocument();
  });
});
