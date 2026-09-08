import { mockFetch, renderWithProviders } from "@/test/utils";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NewJobCardPage } from "./NewJobCardPage";
import { strings } from "./strings";

const client = {
  id: "cl-1",
  client_code: "ACME",
  legal_name: "Acme Switchgear",
  billing_city: "Chennai",
  billing_state: "Tamil Nadu",
  gstin: null,
  is_active: true,
  default_dispatch_policy: "complete_only",
  contacts: [
    {
      id: "ct-1",
      contact_name: "S Ravichandran",
      phone: null,
      email: null,
      is_primary: true,
    },
  ],
};

const category = { id: "cat-1", code: "PANEL", name: "LT panel", is_manufactured: true };

function stubReference(extra: Record<string, unknown> = {}) {
  return mockFetch({
    "GET /api/v1/clients": { items: [client], page: 1, page_size: 50, total: 1, pages: 1 },
    "GET /api/v1/clients/cl-1": client,
    "GET /api/v1/product-categories": { items: [category] },
    "GET /api/v1/enums": {
      dispatch_policy: [
        { value: "complete_only", label: "Complete order only" },
        { value: "partial_allowed", label: "Partial dispatch allowed" },
      ],
      enquiry_source: [{ value: "email", label: "Email" }],
    },
    ...extra,
  });
}

async function chooseClient(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(new RegExp(strings.client, "i")), "Acme");
  await user.click(await screen.findByRole("option", { name: /Acme Switchgear/ }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NewJobCardPage", () => {
  it("seeds the dispatch policy from the client, quietly", async () => {
    const user = userEvent.setup();
    stubReference();
    renderWithProviders(<NewJobCardPage />);

    const policy = screen.getByLabelText(strings.dispatchPolicy) as HTMLSelectElement;
    expect(policy.value).toBe("");

    await chooseClient(user);

    await waitFor(() => expect(policy.value).toBe("complete_only"));
  });

  it("lets the user override the seeded dispatch policy", async () => {
    const user = userEvent.setup();
    stubReference();
    renderWithProviders(<NewJobCardPage />);

    await chooseClient(user);
    const policy = screen.getByLabelText(strings.dispatchPolicy);
    await waitFor(() => expect(policy).toHaveValue("complete_only"));

    await user.selectOptions(policy, "partial_allowed");

    expect(policy).toHaveValue("partial_allowed");
  });

  it("does not re-seed the policy after an override, even when the client detail reloads", async () => {
    const user = userEvent.setup();
    stubReference();
    const { queryClient } = renderWithProviders(<NewJobCardPage />);

    await chooseClient(user);
    const policy = screen.getByLabelText(strings.dispatchPolicy);
    await waitFor(() => expect(policy).toHaveValue("complete_only"));

    await user.selectOptions(policy, "partial_allowed");
    await queryClient.invalidateQueries();

    await waitFor(() => expect(policy).toHaveValue("partial_allowed"));
  });

  it("creates the card, then posts each line separately", async () => {
    const user = userEvent.setup();
    const { calls } = stubReference({
      "POST /api/v1/job-cards": {
        id: "jc-9",
        job_no: "JOB-2026-JAN-0009",
        client: { id: client.id, client_code: client.client_code, legal_name: client.legal_name },
        client_contact: null,
        owner_user: { id: "u-1", username: "rmenon" },
        lifecycle_status: "open",
        enquiry_source: "email",
        dispatch_policy: "complete_only",
        enquiry_date: "2026-03-14",
        required_by: null,
        requirements: {},
      },
      "POST /api/v1/job-cards/jc-9/lines": {
        id: "jl-1",
        line_no: 1,
        product_category: category,
        description: "LT panel",
        quantity: 1,
        line_status: "active",
        required_by: null,
        specs: {},
        current_stage: { id: "s-1", code: "ENQUIRY", name: "Enquiry" },
      },
    });
    renderWithProviders(<NewJobCardPage />);

    await chooseClient(user);

    const firstDescription = screen.getByLabelText(new RegExp(strings.lineDescription, "i"));
    await user.type(firstDescription, "LT panel");
    await user.selectOptions(
      screen.getByLabelText(new RegExp(strings.lineCategory, "i")),
      category.id,
    );

    await user.click(screen.getByRole("button", { name: strings.save }));

    await waitFor(() => {
      expect(
        calls.some((call) => call.url.pathname === "/api/v1/job-cards" && call.method === "POST"),
      ).toBe(true);
    });
    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.url.pathname === "/api/v1/job-cards/jc-9/lines" && call.method === "POST",
        ),
      ).toBe(true);
    });

    const cardCall = calls.find(
      (call) => call.url.pathname === "/api/v1/job-cards" && call.method === "POST",
    );
    expect((cardCall?.body as { client_id: string }).client_id).toBe("cl-1");

    const lineCall = calls.find(
      (call) => call.url.pathname === "/api/v1/job-cards/jc-9/lines" && call.method === "POST",
    );
    expect((lineCall?.body as { description: string }).description).toBe("LT panel");
  });

  it("creates a new client from just a legal name — no client code is asked for", async () => {
    const user = userEvent.setup();
    const { calls } = stubReference({
      "POST /api/v1/clients": {
        id: "cl-new",
        client_code: "CLI-023",
        legal_name: "HelloWorld",
        gstin: null,
        billing_city: null,
        billing_state: null,
        default_dispatch_policy: "partial_allowed",
        is_active: true,
      },
    });
    renderWithProviders(<NewJobCardPage />);

    await user.type(screen.getByLabelText(new RegExp(strings.client, "i")), "HelloWorld");
    await user.click(await screen.findByRole("option", { name: /Add.*HelloWorld/ }));

    // apps/sales/api.py::clients (POST) only requires legal_name now — client_code is
    // server-issued, so there is no code field to fill in before submitting.
    await user.click(screen.getByRole("button", { name: strings.clientCreateSubmit }));

    await waitFor(() => {
      expect(
        calls.some((call) => call.url.pathname === "/api/v1/clients" && call.method === "POST"),
      ).toBe(true);
    });
    const createCall = calls.find(
      (call) => call.url.pathname === "/api/v1/clients" && call.method === "POST",
    );
    expect(createCall?.body).toEqual({ legal_name: "HelloWorld" });
  });

  it("refuses to submit without a client and says why", async () => {
    const user = userEvent.setup();
    const { calls } = stubReference();
    renderWithProviders(<NewJobCardPage />);

    await user.click(screen.getByRole("button", { name: strings.save }));

    expect(await screen.findByText(strings.clientRequired)).toBeInTheDocument();
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("has one required-by date for the whole enquiry, sent to every line", async () => {
    const user = userEvent.setup();
    const { calls } = stubReference({
      "POST /api/v1/job-cards": {
        id: "jc-1",
        job_no: "JOB-2026-JAN-0001",
        client: { id: client.id, client_code: client.client_code, legal_name: client.legal_name },
        client_contact: null,
        owner_user: { id: "u-1", username: "rmenon" },
        lifecycle_status: "open",
        enquiry_source: null,
        dispatch_policy: "complete_only",
        enquiry_date: "2026-09-03",
        required_by: "2026-10-15",
        requirements: {},
      },
      "POST /api/v1/job-cards/jc-1/lines": {
        id: "jl-1",
        line_no: 1,
        product_category: category,
        description: "LT panel",
        quantity: 1,
        line_status: "active",
        required_by: "2026-10-15",
        specs: {},
        current_stage: { id: "s-1", code: "ENQUIRY", name: "Enquiry" },
      },
    });
    renderWithProviders(<NewJobCardPage />);

    // Only one "Required by" field on the whole form — no per-line date to diverge from it.
    expect(screen.getAllByLabelText(strings.requiredBy)).toHaveLength(1);

    await chooseClient(user);
    await user.type(screen.getByLabelText(strings.requiredBy), "2026-10-15");
    await user.type(screen.getByLabelText(new RegExp(strings.lineDescription, "i")), "LT panel");
    await user.selectOptions(
      screen.getByLabelText(new RegExp(strings.lineCategory, "i")),
      category.id,
    );
    await user.click(screen.getByRole("button", { name: strings.save }));

    await waitFor(() => {
      const lineCall = calls.find(
        (call) => call.url.pathname === "/api/v1/job-cards/jc-1/lines" && call.method === "POST",
      );
      expect((lineCall?.body as { required_by: string } | undefined)?.required_by).toBe(
        "2026-10-15",
      );
    });
  });

  it("lets a sales exec add a client contact inline and selects it", async () => {
    const user = userEvent.setup();
    const newContact: {
      id: string;
      contact_name: string;
      phone: string | null;
      email: string | null;
      is_primary: boolean;
    } = {
      id: "ct-new",
      contact_name: "Priya Iyer",
      phone: "+919000000000",
      email: null,
      is_primary: false,
    };
    // GET /clients/cl-1 must reflect the new contact once useCreateContact's onSuccess
    // invalidates it — the real backend would too; a static client object here would
    // silently strip the selection back out (a <select> can't hold a value with no
    // matching <option>).
    let contacts: (typeof newContact)[] = client.contacts;
    const { calls } = stubReference({
      "GET /api/v1/clients/cl-1": () => ({ ...client, contacts }),
      "POST /api/v1/clients/cl-1/contacts": () => {
        contacts = [...contacts, newContact];
        return newContact;
      },
    });
    renderWithProviders(<NewJobCardPage />);

    await chooseClient(user);
    await user.click(screen.getByRole("button", { name: strings.contactCreate }));

    await user.click(screen.getByRole("button", { name: strings.contactCreateSubmit }));
    expect(await screen.findByText(strings.contactCreateNameRequired)).toBeInTheDocument();
    expect(
      calls.some(
        (call) => call.url.pathname === "/api/v1/clients/cl-1/contacts" && call.method === "POST",
      ),
    ).toBe(false);

    await user.type(
      screen.getByLabelText(new RegExp(strings.contactCreateName, "i")),
      "Priya Iyer",
    );
    await user.type(
      screen.getByLabelText(new RegExp(strings.contactCreatePhone, "i")),
      "+919000000000",
    );
    await user.click(screen.getByRole("button", { name: strings.contactCreateSubmit }));

    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.url.pathname === "/api/v1/clients/cl-1/contacts" && call.method === "POST",
        ),
      ).toBe(true);
    });
    const contactSelect = screen.getByLabelText(strings.contact) as HTMLSelectElement;
    await waitFor(() => expect(contactSelect.value).toBe("ct-new"));
  });
});
