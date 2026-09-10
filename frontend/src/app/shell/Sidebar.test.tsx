import type { GrantEntry, Me } from "@/api/types";
import { SessionProvider } from "@/auth/SessionProvider";
import { mockFetch, renderWithProviders } from "@/test/utils";
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";

function me(grants: GrantEntry[], sheetExportUrl: string | null = null): Me {
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
    sheet_export_url: sheetExportUrl,
    grants,
  };
}

const grant = (resource: string, action: string): GrantEntry => ({
  resource,
  action,
  level: 0,
  if_owner: false,
});

function renderSidebar(payload: Me, route?: string) {
  mockFetch({ "GET /api/v1/me": payload });
  return renderWithProviders(
    <SessionProvider>
      <Sidebar />
    </SessionProvider>,
    { route },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Sidebar", () => {
  it("shows only the sections the user's grants cover", async () => {
    renderSidebar(me([grant("job_line", "view"), grant("job_card", "view")]));

    expect(await screen.findByRole("link", { name: "Pipeline board" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Job cards" })).toBeInTheDocument();
    // No client.view grant, so the tab that would only ever 403 is not offered.
    expect(screen.queryByRole("link", { name: "Clients" })).not.toBeInTheDocument();
    // No job_card.create grant either.
    expect(screen.queryByRole("link", { name: "New enquiry" })).not.toBeInTheDocument();
  });

  it("adds the records section once a client grant arrives", async () => {
    renderSidebar(me([grant("client", "view"), grant("job_card", "create")]));

    expect(await screen.findByRole("link", { name: "Clients" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New enquiry" })).toBeInTheDocument();
  });

  it("keeps the dashboard for everyone, even with no grants at all", async () => {
    renderSidebar(me([]));

    expect(await screen.findByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("does not also mark Job cards current while on New enquiry", async () => {
    renderSidebar(me([grant("job_card", "view"), grant("job_card", "create")]), "/job-cards/new");

    expect(await screen.findByRole("link", { name: "New enquiry" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Job cards" })).not.toHaveAttribute("aria-current");
  });

  it("links to the admin panel only with an admin_site:view grant, since that is where masters live", async () => {
    const { unmount } = renderSidebar(me([]));
    expect(await screen.findByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /SR Switchgear Admin/ })).not.toBeInTheDocument();
    unmount();

    renderSidebar(me([grant("admin_site", "view")]));
    expect(await screen.findByRole("link", { name: /SR Switchgear Admin/ })).toBeInTheDocument();
  });

  it("links to the sheet export only with the grant and a configured URL", async () => {
    const { unmount } = renderSidebar(
      me([grant("sheet_export", "view")], "https://docs.google.com/spreadsheets/d/abc/edit"),
    );
    expect(await screen.findByRole("link", { name: /Job Card Ledger/ })).toHaveAttribute(
      "href",
      "https://docs.google.com/spreadsheets/d/abc/edit",
    );
    unmount();

    // Grant without a configured spreadsheet: no dead link.
    const { unmount: unmount2 } = renderSidebar(me([grant("sheet_export", "view")], null));
    expect(await screen.findByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Job Card Ledger/ })).not.toBeInTheDocument();
    unmount2();

    // URL present but no grant: still hidden — the button is a convenience, not the gate.
    renderSidebar(me([], "https://docs.google.com/spreadsheets/d/abc/edit"));
    expect(await screen.findByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Job Card Ledger/ })).not.toBeInTheDocument();
  });
});
