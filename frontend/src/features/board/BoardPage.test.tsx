import type { Board } from "@/api/types";
import { jobLine, stage } from "@/test/factories";
import { mockFetch, renderWithProviders } from "@/test/utils";
import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BoardPage } from "./BoardPage";

/**
 * These stage codes appear nowhere in the source. That is the test: the board is built
 * from whatever GET /board returns, so an administrator adding a stage tomorrow needs no
 * code change — and a hard-coded column would fail here.
 */
const triage = stage({
  id: "st-a",
  code: "TRIAGE",
  name: "Triage",
  sequence_no: 5,
  is_initial: true,
});
const survey = stage({ id: "st-b", code: "SURVEY", name: "Site survey", sequence_no: 15 });
const costing = stage({ id: "st-c", code: "COSTING", name: "Costing", sequence_no: 25 });

function board(): Board {
  return {
    module_code: "sales_pipeline",
    // Deliberately out of order: the board sorts by sequence_no, it does not trust the array.
    columns: [
      {
        stage: costing,
        lines: [
          jobLine({ id: "l-2", line_no: 2, description: "Bus duct run" }),
          jobLine({ id: "l-3", line_no: 3, description: "Capacitor bank" }),
        ],
      },
      {
        stage: triage,
        lines: [jobLine({ id: "l-1", line_no: 1, description: "Feeder pillar" })],
      },
      { stage: survey, lines: [] },
    ],
    total_lines: 3,
  };
}

function stubBoard(payload: Board = board(), extra: Record<string, unknown> = {}) {
  return mockFetch({
    "GET /api/v1/board": payload,
    "GET /api/v1/clients": { items: [], page: 1, page_size: 50, total: 0, pages: 1 },
    "GET /api/v1/product-categories": { items: [] },
    "GET /api/v1/enums": {
      quotation_status: [
        { value: "draft", label: "Draft" },
        { value: "active", label: "Active" },
        { value: "sent", label: "Sent" },
        { value: "accepted", label: "Accepted" },
        { value: "lost", label: "Lost" },
      ],
    },
    ...extra,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BoardPage", () => {
  it("renders one column per stage, in sequence order, from a payload it has never seen", async () => {
    stubBoard();
    renderWithProviders(<BoardPage />);

    expect(await screen.findByRole("heading", { name: "Triage" })).toBeInTheDocument();

    const columns = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(columns).toEqual(["Triage", "Site survey", "Costing"]);
  });

  it("puts each line in the column its current stage keys", async () => {
    stubBoard();
    renderWithProviders(<BoardPage />);

    const costingColumn = await screen.findByRole("region", { name: /Costing, 2 lines/ });
    expect(within(costingColumn).getByText("Bus duct run")).toBeInTheDocument();
    expect(within(costingColumn).getByText("Capacitor bank")).toBeInTheDocument();

    const triageColumn = screen.getByRole("region", { name: /Triage, 1 line/ });
    expect(within(triageColumn).getByText("Feeder pillar")).toBeInTheDocument();
    expect(within(triageColumn).queryByText("Bus duct run")).not.toBeInTheDocument();
  });

  it("keeps an empty stage on the board rather than hiding the column", async () => {
    stubBoard();
    renderWithProviders(<BoardPage />);

    const surveyColumn = await screen.findByRole("region", { name: /Site survey, 0 lines/ });
    expect(within(surveyColumn).getByText("Nothing here")).toBeInTheDocument();
  });

  it("renders only the moves the server offered for a line", async () => {
    const payload = board();
    const triageColumn = payload.columns.find((column) => column.stage.id === triage.id);
    if (!triageColumn) throw new Error("fixture setup");
    triageColumn.lines = [
      jobLine({
        id: "l-1",
        description: "Feeder pillar",
        available_actions: [
          {
            action_code: "send_for_survey",
            to_stage: { id: survey.id, code: survey.code, name: survey.name },
            requires_note: false,
            available: true,
            blocked_by: null,
          },
        ],
      }),
    ];
    stubBoard(payload);
    renderWithProviders(<BoardPage />);

    expect(await screen.findByRole("button", { name: "Send for survey" })).toBeInTheDocument();
    // The line in Costing came back with no actions, so it gets no buttons at all.
    const costingColumn = screen.getByRole("region", { name: /Costing, 2 lines/ });
    expect(within(costingColumn).queryAllByRole("button")).toHaveLength(0);
  });

  it("shows a line's quotation revision and stage when the server sends one", async () => {
    const payload = board();
    const costingColumn = payload.columns.find((column) => column.stage.id === costing.id);
    if (!costingColumn) throw new Error("fixture setup");
    costingColumn.lines = [
      jobLine({
        id: "l-2",
        description: "Bus duct run",
        quotation: { quotation_no: "QT-2026-00001", revision_no: 2, status: "sent" },
      }),
    ];
    stubBoard(payload);
    renderWithProviders(<BoardPage />);

    expect(await screen.findByText("Bus duct run")).toBeInTheDocument();
    expect(screen.getByText("Rev 2")).toBeInTheDocument();
    expect(screen.getByText("Sent")).toBeInTheDocument();
  });

  it("shows no quotation badge for a line that has none", async () => {
    stubBoard();
    renderWithProviders(<BoardPage />);

    expect(await screen.findByText("Feeder pillar")).toBeInTheDocument();
    expect(screen.queryByText(/^Rev /)).not.toBeInTheDocument();
  });

  it("says so when the filters match nothing", async () => {
    stubBoard({
      module_code: "sales_pipeline",
      columns: [
        { stage: triage, lines: [] },
        { stage: survey, lines: [] },
      ],
      total_lines: 0,
    });
    renderWithProviders(<BoardPage />);

    expect(await screen.findByText("No job lines match these filters.")).toBeInTheDocument();
  });
});
