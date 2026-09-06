import type { Stage, TransitionResult } from "@/api/types";
import { action, jobLine } from "@/test/factories";
import { apiError, mockFetch, renderWithProviders } from "@/test/utils";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TransitionDialog } from "./TransitionDialog";
import { strings } from "./strings";

const enquiry: Stage = {
  id: "st-1",
  code: "ENQUIRY",
  name: "Enquiry",
  module_code: "sales_pipeline",
  sequence_no: 10,
  department: null,
  is_initial: true,
  is_terminal: false,
};
const quotation: Stage = {
  ...enquiry,
  id: "st-2",
  code: "QUOTATION",
  name: "Quotation",
  is_initial: false,
};
const lost: Stage = {
  ...enquiry,
  id: "st-9",
  code: "LOST",
  name: "Lost",
  is_initial: false,
  is_terminal: true,
};

function transitionResult(overrides: Partial<TransitionResult> = {}): TransitionResult {
  return {
    id: 1,
    job_line_id: "line-1",
    from_stage: enquiry.code,
    to_stage: quotation.code,
    action_code: "advance",
    performed_at: "2026-03-01T06:00:00Z",
    note: null,
    current_stage: quotation,
    available_actions: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TransitionDialog", () => {
  it("will not submit a move that requires a note until one is written", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch({
      "POST /api/v1/job-lines/line-1/transitions": () =>
        transitionResult({ to_stage: lost.code, current_stage: lost }),
    });

    renderWithProviders(
      <TransitionDialog
        line={jobLine()}
        currentStage={enquiry}
        action={action({
          action_code: "mark_lost",
          to_stage: lost,
          requires_note: true,
        })}
        onClose={vi.fn()}
      />,
    );

    const confirm = screen.getByRole("button", { name: strings.confirm });
    expect(confirm).toBeDisabled();
    expect(screen.getByText(strings.noteRequiredHint)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/note/i), "Client bought elsewhere.");
    expect(confirm).toBeEnabled();

    await user.click(confirm);

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.body).toEqual({
      action_code: "mark_lost",
      note: "Client bought elsewhere.",
    });
  });

  it("submits without a note when the rule does not ask for one", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { calls } = mockFetch({
      "POST /api/v1/job-lines/line-1/transitions": () => transitionResult(),
    });

    renderWithProviders(
      <TransitionDialog
        line={jobLine()}
        currentStage={enquiry}
        action={action({ action_code: "advance", to_stage: quotation })}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByRole("button", { name: strings.confirm }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls[0]?.body).toEqual({ action_code: "advance" });
  });

  it("says the line has already moved on a 409, and does not retry", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { calls } = mockFetch({
      "POST /api/v1/job-lines/line-1/transitions": () =>
        apiError(409, "stale_transition", "This line has moved."),
    });

    renderWithProviders(
      <TransitionDialog
        line={jobLine()}
        currentStage={enquiry}
        action={action({ action_code: "advance", to_stage: quotation })}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByRole("button", { name: strings.confirm }));

    expect(await screen.findByText(strings.staleTitle)).toBeInTheDocument();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    // One attempt. Replaying the action against a stage the line has left is not a fix.
    expect(calls).toHaveLength(1);
  });

  it("shows the server's reason when a rule refuses the move", async () => {
    const user = userEvent.setup();
    mockFetch({
      "POST /api/v1/job-lines/line-1/transitions": () =>
        apiError(422, "rule_violation", "A quotation must be sent first."),
    });

    renderWithProviders(
      <TransitionDialog
        line={jobLine()}
        currentStage={enquiry}
        action={action({ action_code: "confirm", to_stage: quotation })}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: strings.confirm }));

    expect(await screen.findByText("A quotation must be sent first.")).toBeInTheDocument();
  });
});
