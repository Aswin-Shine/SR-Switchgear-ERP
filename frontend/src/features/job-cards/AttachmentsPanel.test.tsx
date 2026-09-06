import type { Attachment, GrantEntry, Me } from "@/api/types";
import { SessionProvider } from "@/auth/SessionProvider";
import { mockFetch, renderWithProviders } from "@/test/utils";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AttachmentsPanel } from "./AttachmentsPanel";
import { strings } from "./strings";

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
    grants,
  };
}

const grant = (resource: string, action: string): GrantEntry => ({
  resource,
  action,
  level: 0,
  if_owner: false,
});

const attachment: Attachment = {
  id: "at-1",
  label: null,
  filename: "site-photo.jpg",
  mime_type: "image/jpeg",
  byte_size: 2048,
  job_line_id: null,
  attached_by: "rmenon",
  attached_at: "2026-09-04T10:00:00Z",
};

function renderPanel(payload: Me, extra: Record<string, unknown> = {}) {
  const { calls } = mockFetch({
    "GET /api/v1/me": payload,
    "GET /api/v1/job-cards/jc-1/attachments": { items: [attachment] },
    ...extra,
  });
  const result = renderWithProviders(
    <SessionProvider>
      <AttachmentsPanel jobCardId="jc-1" />
    </SessionProvider>,
  );
  return { ...result, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AttachmentsPanel", () => {
  it("does not offer Remove to someone who can only view the job card", async () => {
    renderPanel(me([grant("job_card", "view")]));

    expect(await screen.findByText("site-photo.jpg")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: strings.attachmentRemove }),
    ).not.toBeInTheDocument();
  });

  it("asks for confirmation, then removes the attachment", async () => {
    const user = userEvent.setup();
    const { calls } = renderPanel(me([grant("job_card", "edit")]), {
      "DELETE /api/v1/job-cards/jc-1/attachments/at-1": {},
    });

    await screen.findByText("site-photo.jpg");
    await user.click(screen.getByRole("button", { name: strings.attachmentRemove }));

    expect(await screen.findByText(strings.attachmentRemoveTitle)).toBeInTheDocument();
    expect(screen.getByText(strings.attachmentRemoveBody("site-photo.jpg"))).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: strings.attachmentRemoveConfirm }));

    await waitFor(() => {
      expect(
        calls.some(
          (call) =>
            call.url.pathname === "/api/v1/job-cards/jc-1/attachments/at-1" &&
            call.method === "DELETE",
        ),
      ).toBe(true);
    });
  });

  it("cancelling the dialog leaves the attachment untouched", async () => {
    const user = userEvent.setup();
    const { calls } = renderPanel(me([grant("job_card", "edit")]));

    await screen.findByText("site-photo.jpg");
    await user.click(screen.getByRole("button", { name: strings.attachmentRemove }));
    await screen.findByText(strings.attachmentRemoveTitle);

    await user.click(screen.getByRole("button", { name: strings.cancel }));

    expect(screen.queryByText(strings.attachmentRemoveTitle)).not.toBeInTheDocument();
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });
});
